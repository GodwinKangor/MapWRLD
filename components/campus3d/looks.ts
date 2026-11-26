// Scene looks: full-screen style passes over the finished frame (the gods-eye-view approach),
// so a look never touches materials, the GLB, or the evidence highlight texture.
// "standard" bypasses post-processing entirely and costs nothing. The engine draws markers
// after the look, so pins and badges keep their colors whichever look is on.

import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { ShaderPass } from "three/examples/jsm/postprocessing/ShaderPass.js";

export type Look = "standard" | "focus" | "blueprint";
export const LOOKS: { id: Look; label: string }[] = [
  { id: "standard", label: "Standard" },
  { id: "focus", label: "Focus" },
  { id: "blueprint", label: "Blueprint" },
];

const VERTEX = /* glsl */ `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

// both run after OutputPass, on display-ready (tone-mapped, sRGB) color
const FRAGMENTS: Record<Exclude<Look, "standard">, string> = {
  // mute the map so saturated things (evidence tint, energy networks, selection) carry the eye
  focus: /* glsl */ `
uniform sampler2D tDiffuse;
varying vec2 vUv;
void main() {
  vec3 color = texture2D(tDiffuse, vUv).rgb;
  float luma = dot(color, vec3(0.299, 0.587, 0.114));
  float high = max(color.r, max(color.g, color.b));
  float saturation = high > 0.0 ? (high - min(color.r, min(color.g, color.b))) / high : 0.0;
  float keep = smoothstep(0.42, 0.7, saturation);
  vec3 muted = mix(vec3(0.12, 0.13, 0.12), vec3(0.93, 0.92, 0.88), luma);
  gl_FragColor = vec4(mix(muted, color, keep), 1.0);
}`,
  // luminance edges as drafting lines on blue paper
  blueprint: /* glsl */ `
uniform sampler2D tDiffuse;
uniform vec2 texel;
varying vec2 vUv;
float luma(vec2 offset) { return dot(texture2D(tDiffuse, vUv + offset * texel).rgb, vec3(0.299, 0.587, 0.114)); }
void main() {
  float tl = luma(vec2(-1.0, 1.0)), t = luma(vec2(0.0, 1.0)), tr = luma(vec2(1.0, 1.0));
  float l = luma(vec2(-1.0, 0.0)), c = luma(vec2(0.0)), r = luma(vec2(1.0, 0.0));
  float bl = luma(vec2(-1.0, -1.0)), b = luma(vec2(0.0, -1.0)), br = luma(vec2(1.0, -1.0));
  float gx = tr + 2.0 * r + br - tl - 2.0 * l - bl;
  float gy = tl + 2.0 * t + tr - bl - 2.0 * b - br;
  // high threshold: only strong outlines (roofs, roads) draw, not the aerial photo's texture
  float edge = smoothstep(0.45, 0.9, length(vec2(gx, gy)));
  vec3 paper = mix(vec3(0.04, 0.13, 0.25), vec3(0.09, 0.24, 0.40), smoothstep(0.2, 0.8, c));
  gl_FragColor = vec4(mix(paper, vec3(0.84, 0.93, 1.0), edge), 1.0);
}`,
};

export class LookPipeline {
  private readonly composer: EffectComposer;
  private readonly stylePass: ShaderPass;
  private readonly renderPass: RenderPass;

  constructor(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.Camera, look: Exclude<Look, "standard">, samples: number) {
    // HDR target with MSAA, since the canvas's own antialiasing doesn't apply to offscreen passes
    const target = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples });
    this.composer = new EffectComposer(renderer, target);
    this.renderPass = new RenderPass(scene, camera);
    this.stylePass = new ShaderPass({
      uniforms: { tDiffuse: { value: null }, texel: { value: new THREE.Vector2() } },
      vertexShader: VERTEX,
      fragmentShader: FRAGMENTS[look],
    });
    this.composer.addPass(this.renderPass);
    this.composer.addPass(new OutputPass()); // tone mapping + sRGB, so the look sees final colors
    this.composer.addPass(this.stylePass);
  }

  setSize(width: number, height: number, pixelRatio: number) {
    this.composer.setPixelRatio(pixelRatio);
    this.composer.setSize(width, height);
    (this.stylePass.uniforms.texel.value as THREE.Vector2).set(1 / (width * pixelRatio), 1 / (height * pixelRatio));
  }

  render() {
    this.composer.render();
  }

  dispose() {
    this.stylePass.dispose();
    this.composer.dispose();
  }
}
