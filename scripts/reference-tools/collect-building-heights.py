"""Sample NH GRANIT nDSM inside OSM footprints; retain provenance and uncertainty.

Requires requests, numpy, Pillow. Run with --footprints source.geojson.
The cached raster is an older surface-height estimate, not a current survey.
"""
import argparse
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
CAMPUS = ROOT / 'public/models/dartmouth-campus'
DATA = ROOT / 'assets/height-data'
SERVICE = 'https://nhgeodata.unh.edu/image/rest/services/ImageServices/nDSM_NW_HS_NH/ImageServer'


def rings(geometry):
    if geometry['type'] == 'Polygon':
        return [geometry['coordinates']]
    if geometry['type'] == 'MultiPolygon':
        return geometry['coordinates']
    raise ValueError(f"Unsupported footprint: {geometry['type']}")


def inside_ring(x, y, ring):
    inside = np.zeros(x.shape, dtype=bool)
    edge_distance = np.full(x.shape, np.inf)
    latitude = float(np.mean(y))
    lon_m = 111320 * math.cos(math.radians(latitude))
    lat_m = 111132
    for a, b in zip(ring, ring[1:] + ring[:1]):
        ax, ay = a[:2]; bx, by = b[:2]
        if by != ay:
            inside ^= ((ay > y) != (by > y)) & (x < (bx-ax)*(y-ay)/(by-ay)+ax)
        vx, vy = (bx-ax)*lon_m, (by-ay)*lat_m
        px, py = (x-ax)*lon_m, (y-ay)*lat_m
        t = np.clip((px*vx+py*vy)/max(vx*vx+vy*vy, 1e-12), 0, 1)
        edge_distance = np.minimum(edge_distance, np.hypot(px-t*vx, py-t*vy))
    return inside, edge_distance


def sample(geometry, raster, extent):
    coordinates = [p for polygon in rings(geometry) for ring in polygon for p in ring]
    west, south, east, north = [extent[k] for k in ('xmin','ymin','xmax','ymax')]
    rows, cols = raster.shape
    dx, dy = (east-west)/cols, (north-south)/rows
    left = max(0, math.floor((min(p[0] for p in coordinates)-west)/dx))
    right = min(cols, math.ceil((max(p[0] for p in coordinates)-west)/dx))
    top = max(0, math.floor((north-max(p[1] for p in coordinates))/dy))
    bottom = min(rows, math.ceil((north-min(p[1] for p in coordinates))/dy))
    if left >= right or top >= bottom:
        return {'accepted': False, 'reason': 'outside_raster'}
    x, y = np.meshgrid(west+(np.arange(left,right)+.5)*dx,
                       north-(np.arange(top,bottom)+.5)*dy)
    mask = np.zeros(x.shape, dtype=bool)
    for polygon in rings(geometry):
        part, distance = inside_ring(x,y,polygon[0])
        part &= distance >= 1.0  # Avoid roof edges and neighboring trees.
        for hole in polygon[1:]:
            hole_inside, hole_distance = inside_ring(x,y,hole)
            part &= ~hole_inside & (hole_distance >= 1.0)
        mask |= part
    values = raster[top:bottom,left:right][mask]
    valid = values[np.isfinite(values) & (values >= 0) & (values < 100)]
    stats = {'sampleCount': int(valid.size), 'interiorPixelCount': int(values.size),
             'accepted': False}
    if valid.size < 6 or valid.size < .8*values.size:
        return {**stats, 'reason': 'insufficient_valid_interior_pixels'}
    q25,q50,q75,q90 = np.percentile(valid,[25,50,75,90])
    stats.update({f'p{n}Meters': round(float(v),2) for n,v in zip((25,50,75,90),(q25,q50,q75,q90))})
    if q50 < 2.5 or q50 > 60:
        return {**stats, 'reason': 'implausible_building_height_or_missing_historical_building'}
    if q75-q25 > 5 or q90-q25 > 10:
        return {**stats, 'reason': 'variable_surface_possible_trees_or_complex_roof'}
    return {**stats, 'accepted': True, 'heightMeters': round(float(q50),2),
            'reason': 'median_of_interior_surface_pixels'}


def parse_height(value):
    if not value:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(m|meters?|ft|feet|')?\s*", str(value),re.I)
    if not match:
        return None
    height = float(match[1]) * (.3048 if (match[2] or '').lower() in ('ft','feet',"'") else 1)
    return round(height,2) if 2.5 <= height <= 100 else None


def collect(source):
    DATA.mkdir(parents=True,exist_ok=True)
    footprints = json.loads(source.read_text())
    polygons = [p for f in footprints['features'] for polygon in rings(f['geometry']) for ring in polygon for p in ring]
    bbox = [min(p[0] for p in polygons)-.00005,min(p[1] for p in polygons)-.00005,
            max(p[0] for p in polygons)+.00005,max(p[1] for p in polygons)+.00005]
    raster_path, metadata_path = DATA/'campus-ndsm.tif', DATA/'campus-ndsm.json'
    params = {'f':'json','bbox':','.join(map(str,bbox)),'bboxSR':4326,'imageSR':4326,
              'size':'1000,1000','format':'tiff','pixelType':'F32','interpolation':'RSP_NearestNeighbor'}
    if not raster_path.exists() or not metadata_path.exists():
        response = requests.get(SERVICE+'/exportImage',params=params,timeout=90)
        response.raise_for_status(); meta = response.json()
        if 'error' in meta:
            raise RuntimeError(meta['error'])
        image = requests.get(meta['href'],timeout=90);image.raise_for_status()
        raster_path.write_bytes(image.content)
        meta.update(service=SERVICE,request=params,retrievedAt=datetime.now(timezone.utc).isoformat(),
                    sha256=hashlib.sha256(image.content).hexdigest())
        metadata_path.write_text(json.dumps(meta,indent=2)+'\n')
    meta = json.loads(metadata_path.read_text())
    assert meta['request'] == params, 'Cached raster does not match footprint extent'
    assert meta['sha256'] == hashlib.sha256(raster_path.read_bytes()).hexdigest()
    raster = np.asarray(Image.open(raster_path), dtype=float)
    assert raster.ndim == 2 and meta['extent']['spatialReference']['wkid'] == 4326
    names = {x['osmId']:x for x in json.loads((ROOT/'public/models/dartmouth-energy-twin/reports/osm-campus-names.json').read_text())['buildings']}
    alignment = {x['node']:x['residualMeters'] for x in json.loads((CAMPUS/'georeference-report.json').read_text())['controls']}
    parts = json.loads((ROOT/'public/models/dartmouth-energy-twin/renders/parts-manifest.json').read_text())['buildings']
    part_names = {'way/'+x['name'].split('__way_')[-1]:x for x in parts}
    records = []
    for feature in footprints['features']:
        tags = feature['properties']; osm_id = feature.get('id') or tags['@id']
        part = part_names.get(osm_id)
        if not part:
            continue
        osm = names.get(osm_id,{})
        residual = alignment.get('part::'+part['name'])
        stats = sample(feature['geometry'],raster,meta['extent'])
        height = parse_height(tags.get('height') or tags.get('building:height'))
        method = 'osm_reported_height' if height else 'unknown'
        if height is None and stats['accepted']:
            height,method = stats['heightMeters'],'lidar_estimate'
        levels = tags.get('building:levels')
        if height is None and levels and re.fullmatch(r'\d+(?:\.\d+)?',str(levels)) and 1 <= float(levels) <= 20:
            height,method = round(float(levels)*3.2,2),'floor_estimate'
        records.append({'osmId':osm_id,'name':osm.get('name',tags.get('name',osm_id)),
                        'node':'part::'+part['name'],'heightMeters':height,'method':method,
                        'originalModelHeightMeters':part['dimensions']['z'],
                        'footprintAlignmentResidualMeters':None if residual is None else round(residual,3),
                        'modelFootprintAligned':residual is not None and residual <= 2,
                        'osmHeight':tags.get('height') or tags.get('building:height'),
                        'osmLevels':levels,'lidar':stats,'reviewRequired':True,
                        'sourceUrl':f'https://www.openstreetmap.org/{osm_id}' if method.startswith(('osm_','floor_')) else SERVICE,
                        'sourceAsOf':'OSM source snapshot' if method.startswith(('osm_','floor_')) else 'LiDAR collections available January 2020'})
    (DATA/'building-footprints.geojson').write_text(json.dumps(footprints,separators=(',',':'))+'\n')
    report = {'generatedAt':datetime.now(timezone.utc).isoformat(),'units':'meters',
              'source':{'service':SERVICE,'credit':'NH GRANIT, University of New Hampshire',
                        'dataset':'2-meter nDSM from LiDAR collections available January 2020',
                        'rasterSha256':meta['sha256'],'footprintsSha256':hashlib.sha256(source.read_bytes()).hexdigest()},
              'limitations':['Surface estimates may include vegetation and rooftop equipment.',
                             'Historical LiDAR may predate construction or renovations.',
                             'Floor estimates assume 3.2 meters per above-ground floor; roofs are not separately modeled.',
                             'Unaligned model identities and detailed geometry must not be automatically rescaled.'],
              'counts':dict(Counter(x['method'] for x in records)), 'buildings':records}
    (CAMPUS/'building-heights.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['counts'],indent=2),flush=True)
    print('Aligned with usable height:',sum(x['modelFootprintAligned'] and x['heightMeters'] is not None for x in records),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--footprints',type=Path,required=True)
    collect(parser.parse_args().footprints)
