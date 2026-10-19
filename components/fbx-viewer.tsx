"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { FBXLoader } from "three/examples/jsm/loaders/FBXLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

type Status = "loading" | "ready" | "error";

export default function FbxViewer({ src, label }: { src?: string; label?: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<Status>("loading");

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !src) {
      setStatus("error");
      return;
    }

    setStatus("loading");
    let cancelled = false;
    let frameId = 0;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xece9df);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const sun = new THREE.DirectionalLight(0xffffff, 1.1);
    sun.position.set(80, 140, 100);
    scene.add(sun);
    const fill = new THREE.DirectionalLight(0xffffff, 0.35);
    fill.position.set(-80, 40, -60);
    scene.add(fill);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    const resize = () => {
      const width = container.clientWidth || 1;
      const height = container.clientHeight || 1;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    };
    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);

    const animate = () => {
      controls.update();
      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };
    animate();

    let loadedRoot: THREE.Object3D | null = null;
    new FBXLoader().load(
      src,
      (object) => {
        if (cancelled) return;
        const box = new THREE.Box3().setFromObject(object);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        object.position.sub(center);

        const radius = Math.max(size.x, size.y, size.z, 1) * 0.5;
        camera.position.set(radius * 1.6, radius * 1.3, radius * 1.6);
        camera.near = radius / 100;
        camera.far = radius * 50;
        camera.updateProjectionMatrix();
        controls.target.set(0, 0, 0);
        controls.update();

        scene.add(object);
        loadedRoot = object;
        setStatus("ready");
      },
      undefined,
      () => {
        if (!cancelled) setStatus("error");
      },
    );

    return () => {
      cancelled = true;
      cancelAnimationFrame(frameId);
      resizeObserver.disconnect();
      controls.dispose();
      if (loadedRoot) disposeObject(loadedRoot);
      renderer.dispose();
      if (renderer.domElement.parentNode === container) container.removeChild(renderer.domElement);
    };
  }, [src]);

  return (
    <div className="model-panel">
      <div className="model-panel-canvas" ref={containerRef} />
      {status !== "ready" && (
        <div className="model-panel-status">
          {status === "loading" ? <span>Loading {label ?? "FBX"}…</span> : <span>No FBX export available</span>}
        </div>
      )}
    </div>
  );
}

function disposeObject(root: THREE.Object3D) {
  root.traverse((child) => {
    if (!(child instanceof THREE.Mesh)) return;
    child.geometry?.dispose();
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    for (const material of materials) {
      for (const key of Object.keys(material) as (keyof THREE.Material)[]) {
        const value = material[key];
        if (value && typeof value === "object" && "isTexture" in value) (value as THREE.Texture).dispose();
      }
      material.dispose();
    }
  });
}
