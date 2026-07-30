const NAME_OVERRIDES = new Map(Object.entries({
  "63 south main street parking deck": "South Main Street Parking Garage",
  "alexis boss tennis": "Alexis Boss Tennis Center",
  "alexis boss tennis center": "Alexis Boss Tennis Center",
  "class of 1978 life sciences": "Class of 1978 Life Sciences Center",
  "life sciences center": "Class of 1978 Life Sciences Center",
  "baker library": "Baker-Berry Library",
  "berry library": "Baker-Berry Library",
  "baker berry library": "Baker-Berry Library",
  "hopkins center": "Hopkins Center for the Arts",
  "the hop": "Hopkins Center for the Arts",
  "foco": "Class of 1953 Commons",
  "53 commons": "Class of 1953 Commons",
  "1953 commons": "Class of 1953 Commons",
  "thayer school of engineering": "Thayer School of Engineering",
  "tuck school of business": "Tuck School of Business",
  "geisel school of medicine": "Geisel School of Medicine",
}));

const BAD_GENERATED_NAMES = [
  /^building\s+\d+$/i,
  /^areasfbx/i,
  /^p?cube\d*$/i,
];

export function getCampusBuildingName(tags = {}, wayId = "") {
  const address = [tags["addr:housenumber"], tags["addr:street"]].filter(Boolean).join(" ");
  const rawName = tags.name ?? tags["addr:housename"] ?? address ?? "";
  const fallback = rawName || `Building ${wayId}`;
  const cleaned = cleanName(fallback);
  const override = NAME_OVERRIDES.get(normalizeName(cleaned));

  return {
    name: override ?? cleaned,
    rawName: fallback,
    hasRealName: Boolean(tags.name || tags["addr:housename"]),
    isAddressOnly: Boolean(address && !tags.name && !tags["addr:housename"]),
    isGenerated: BAD_GENERATED_NAMES.some((pattern) => pattern.test(cleaned)),
  };
}

export function normalizeName(value) {
  return String(value)
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function cleanName(value) {
  return String(value)
    .replace(/\s+/g, " ")
    .replace(/\bCtr\b\.?/gi, "Center")
    .replace(/\bLib\b\.?/gi, "Library")
    .trim();
}
