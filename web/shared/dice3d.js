// 3D dice for the table screen.
// The server decides every result; this module only animates real-looking dice
// that tumble across the table and come to rest on exactly that face.

import * as THREE from "/static/vendor/three.module.min.js";

const UP = new THREE.Vector3(0, 1, 0);

// ── geometry ─────────────────────────────────────────────────────────────

function facesFromGeometry(geom) {
  const g = geom.index ? geom.toNonIndexed() : geom;
  const pos = g.getAttribute("position");
  const faces = [];
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  for (let i = 0; i < pos.count; i += 3) {
    a.fromBufferAttribute(pos, i); b.fromBufferAttribute(pos, i + 1); c.fromBufferAttribute(pos, i + 2);
    const n = new THREE.Vector3().subVectors(c, b).cross(new THREE.Vector3().subVectors(a, b)).normalize();
    let face = faces.find((f) => f.normal.dot(n) > 0.995);
    if (!face) { face = { normal: n.clone(), verts: [] }; faces.push(face); }
    for (const v of [a, b, c]) {
      if (!face.verts.some((w) => w.distanceToSquared(v) < 1e-6)) face.verts.push(v.clone());
    }
  }
  for (const f of faces) orderFace(f);
  return faces;
}

function orderFace(f) {
  const center = f.verts.reduce((s, v) => s.add(v), new THREE.Vector3()).multiplyScalar(1 / f.verts.length);
  if (f.normal.dot(center) < 0) f.normal.negate();
  const u = new THREE.Vector3().subVectors(f.verts[0], center).normalize();
  const w = new THREE.Vector3().crossVectors(f.normal, u);
  f.verts.sort((p, q) => {
    const dp = new THREE.Vector3().subVectors(p, center), dq = new THREE.Vector3().subVectors(q, center);
    return Math.atan2(dp.dot(w), dp.dot(u)) - Math.atan2(dq.dot(w), dq.dot(u));
  });
  f.center = center;
}

function d10Faces() {
  const verts = [];
  const top = new THREE.Vector3(0, 1, 0), bottom = new THREE.Vector3(0, -1, 0);
  for (let i = 0; i < 10; i++) {
    const ang = (i * Math.PI * 2) / 10;
    verts.push(new THREE.Vector3(Math.cos(ang), i % 2 === 0 ? 0.105 : -0.105, Math.sin(ang)));
  }
  const faces = [];
  for (let i = 0; i < 10; i += 2) {
    faces.push({ verts: [top, verts[i], verts[(i + 1) % 10], verts[(i + 2) % 10]].map((v) => v.clone()) });
    faces.push({ verts: [bottom, verts[(i + 1) % 10], verts[(i + 2) % 10], verts[(i + 3) % 10]].map((v) => v.clone()) });
  }
  for (const f of faces) {
    const [p0, p1, p2] = f.verts;
    f.normal = new THREE.Vector3().subVectors(p2, p1).cross(new THREE.Vector3().subVectors(p0, p1)).normalize();
    orderFace(f);
  }
  return faces;
}

const FACE_CACHE = {};
function facesFor(sides) {
  if (FACE_CACHE[sides]) return FACE_CACHE[sides];
  let faces;
  switch (sides) {
    case 4: faces = facesFromGeometry(new THREE.TetrahedronGeometry(1)); break;
    case 6: faces = facesFromGeometry(new THREE.BoxGeometry(1.3, 1.3, 1.3)); break;
    case 8: faces = facesFromGeometry(new THREE.OctahedronGeometry(1)); break;
    case 10: case 100: faces = d10Faces(); break;
    case 12: faces = facesFromGeometry(new THREE.DodecahedronGeometry(1)); break;
    default: faces = facesFromGeometry(new THREE.IcosahedronGeometry(1)); break;
  }
  FACE_CACHE[sides] = faces;
  return faces;
}

function faceLabel(sides, i) {
  if (sides === 100) return String(i * 10).padStart(2, "0");
  if (sides === 10) return String(i === 9 ? 0 : i + 1);
  return String(i + 1);
}

function makeTexture(label, color, ink) {
  const s = 256;
  const cv = document.createElement("canvas");
  cv.width = cv.height = s;
  const ctx = cv.getContext("2d");
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, s, s);
  const grd = ctx.createRadialGradient(s / 2, s / 2, s * 0.1, s / 2, s / 2, s * 0.7);
  grd.addColorStop(0, "rgba(255,255,255,0.10)");
  grd.addColorStop(1, "rgba(0,0,0,0.25)");
  ctx.fillStyle = grd;
  ctx.fillRect(0, 0, s, s);
  ctx.fillStyle = ink;
  ctx.font = `bold ${label.length > 1 ? 92 : 112}px Cinzel, Georgia, serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.shadowColor = "rgba(0,0,0,0.6)";
  ctx.shadowBlur = 6;
  ctx.fillText(label, s / 2, s / 2 + 6);
  if (label === "6" || label === "9") ctx.fillRect(s / 2 - 22, s / 2 + 52, 44, 7);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

function buildDie(sides, color, ink) {
  const faces = facesFor(sides);
  const positions = [], uvs = [], groups = [];
  let vi = 0;
  faces.forEach((f, fi) => {
    const u = new THREE.Vector3().subVectors(f.verts[0], f.center).normalize();
    const w = new THREE.Vector3().crossVectors(f.normal, u);
    const R = Math.max(...f.verts.map((v) => v.distanceTo(f.center)));
    const uv = (p) => {
      const d = new THREE.Vector3().subVectors(p, f.center);
      return [0.5 + (d.dot(u) / (2 * R)) * 0.95, 0.5 + (d.dot(w) / (2 * R)) * 0.95];
    };
    const start = vi;
    for (let k = 1; k < f.verts.length - 1; k++) {
      for (const p of [f.verts[0], f.verts[k], f.verts[k + 1]]) {
        positions.push(p.x, p.y, p.z);
        uvs.push(...uv(p));
        vi++;
      }
    }
    groups.push([start, vi - start, fi]);
  });
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geom.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
  for (const [s, c, m] of groups) geom.addGroup(s, c, m);
  geom.computeVertexNormals();
  const mats = faces.map((_, i) => new THREE.MeshStandardMaterial({
    map: makeTexture(faceLabel(sides, i), color, ink), roughness: 0.35, metalness: 0.15,
    transparent: true, flatShading: true,
  }));
  const mesh = new THREE.Mesh(geom, mats);
  mesh.castShadow = true;
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geom, 20),
    new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35 }));
  mesh.add(edges);
  const scale = sides === 6 ? 0.62 : sides === 4 ? 0.85 : 0.72;
  mesh.scale.setScalar(scale);
  return { mesh, faces, radius: scale * (sides === 6 ? 0.9 : 0.8) };
}

function faceIndexFor(sides, value) {
  if (sides === 100) return Math.max(0, Math.min(9, Math.floor(value / 10) % 10));
  if (sides === 10) return value === 10 ? 9 : value - 1;
  return Math.max(0, Math.min(sides - 1, value - 1));
}

// ── sound ────────────────────────────────────────────────────────────────

let audioCtx = null;
function clack(intensity = 1) {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const dur = 0.05;
    const buf = audioCtx.createBuffer(1, audioCtx.sampleRate * dur, audioCtx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / d.length, 3);
    const src = audioCtx.createBufferSource();
    src.buffer = buf;
    const filt = audioCtx.createBiquadFilter();
    filt.type = "bandpass";
    filt.frequency.value = 1800 + Math.random() * 1500;
    const gain = audioCtx.createGain();
    gain.gain.value = 0.25 * Math.min(1, intensity);
    src.connect(filt).connect(gain).connect(audioCtx.destination);
    src.start();
  } catch (e) { /* audio is optional */ }
}

// ── tray ─────────────────────────────────────────────────────────────────

export class DiceTray {
  constructor(container, { sound = true } = {}) {
    this.container = container;
    this.sound = sound;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    this.camera.position.set(0, 13, 7.5);
    this.camera.lookAt(0, 0, 0.6);
    this.scene.add(new THREE.AmbientLight(0xfff2dd, 0.9));
    const key = new THREE.DirectionalLight(0xffe7c2, 2.2);
    key.position.set(-4, 12, 6);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    Object.assign(key.shadow.camera, { left: -10, right: 10, top: 10, bottom: -10 });
    this.scene.add(key);
    const rim = new THREE.PointLight(0x8fb7ff, 30, 30);
    rim.position.set(6, 6, -6);
    this.scene.add(rim);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.ShadowMaterial({ opacity: 0.35 }));
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    this.scene.add(floor);
    this.dice = [];
    this.running = false;
    this.bounds = { x: 6, z: 3.6 };
    this._resize = () => this.resize();
    window.addEventListener("resize", this._resize);
    this.resize();
  }

  resize() {
    const w = this.container.clientWidth || window.innerWidth;
    const h = this.container.clientHeight || window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    const halfH = Math.tan((this.camera.fov * Math.PI) / 360) * this.camera.position.length();
    this.bounds = { x: Math.max(3, halfH * this.camera.aspect * 0.55), z: Math.max(2.4, halfH * 0.42) };
  }

  clear() {
    for (const d of this.dice) this.scene.remove(d.mesh);
    this.dice = [];
  }

  /**
   * Throw dice. specs: [{sides, value, kept}], opts: {color, ink, duration}
   * Resolves when every die has settled on its target face.
   */
  roll(specs, opts = {}) {
    this.clear();
    const color = opts.color || "#7a1f1f";
    const ink = opts.ink || "#f6e7c1";
    const duration = opts.duration || 2.2;
    const n = specs.length;
    specs.forEach((spec, i) => {
      const sides = spec.sides === 2 || spec.sides === 3 ? 6 : spec.sides;
      const die = buildDie(sides, color, ink);
      const fromLeft = Math.random() < 0.5;
      const lane = n === 1 ? 0 : (i / (n - 1) - 0.5) * Math.min(this.bounds.z * 1.4, n * 1.2);
      const start = new THREE.Vector3((fromLeft ? -1 : 1) * (this.bounds.x + 2), 3.2 + Math.random() * 1.5, lane);
      const settleX = (n === 1 ? 0 : (i / (n - 1) - 0.5) * Math.min(this.bounds.x * 1.3, n * 1.5)) + (Math.random() - 0.5) * 0.6;
      const vel = new THREE.Vector3((settleX - start.x) * (1.05 + Math.random() * 0.25), 1.5 + Math.random() * 2, (Math.random() - 0.5) * 2);
      const ang = new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).normalize()
        .multiplyScalar(14 + Math.random() * 10);
      die.mesh.position.copy(start);
      die.mesh.quaternion.setFromEuler(new THREE.Euler(Math.random() * 6, Math.random() * 6, Math.random() * 6));
      const face = die.faces[faceIndexFor(sides, spec.value)];
      const align = new THREE.Quaternion().setFromUnitVectors(face.normal.clone().normalize(), UP);
      const yaw = new THREE.Quaternion().setFromAxisAngle(UP, Math.random() * Math.PI * 2);
      const target = yaw.multiply(align);
      this.scene.add(die.mesh);
      this.dice.push({ ...die, spec, vel, ang, target, t: 0, lastBounce: 0,
        settleX, settleZ: lane * 0.6 + (Math.random() - 0.5) * 0.5 });
    });
    return new Promise((resolve) => {
      this.duration = duration;
      this.onDone = resolve;
      this.elapsed = 0;
      if (!this.running) { this.running = true; this.last = performance.now(); requestAnimationFrame((t) => this.tick(t)); }
    });
  }

  tick(now) {
    const dt = Math.min(0.033, (now - this.last) / 1000);
    this.last = now;
    this.elapsed += dt;
    const T = this.duration;
    const settleStart = T * 0.58;
    const g = 22;
    for (const d of this.dice) {
      const m = d.mesh;
      if (this.elapsed < settleStart) {
        d.vel.y -= g * dt;
        m.position.addScaledVector(d.vel, dt);
        if (m.position.y < d.radius) {
          m.position.y = d.radius;
          if (Math.abs(d.vel.y) > 1.2 && this.sound && this.elapsed - d.lastBounce > 0.08) {
            clack(Math.abs(d.vel.y) / 8);
            d.lastBounce = this.elapsed;
          }
          d.vel.y = -d.vel.y * 0.42;
          d.vel.x *= 0.82; d.vel.z *= 0.82;
          d.ang.multiplyScalar(0.78);
        }
        if (Math.abs(m.position.x) > this.bounds.x + 2.5 && this.elapsed > 0.4) { d.vel.x *= -0.6; }
        if (Math.abs(m.position.z) > this.bounds.z) { d.vel.z *= -0.6; m.position.z = Math.sign(m.position.z) * this.bounds.z; }
        const w = d.ang.length();
        if (w > 0) {
          const dq = new THREE.Quaternion().setFromAxisAngle(d.ang.clone().normalize(), w * dt);
          m.quaternion.premultiply(dq);
        }
        d.settleFrom = m.quaternion.clone();
        d.posFrom = m.position.clone();
      } else {
        const k = Math.min(1, (this.elapsed - settleStart) / (T - settleStart));
        const e = 1 - Math.pow(1 - k, 3);
        m.quaternion.slerpQuaternions(d.settleFrom, d.target, e);
        const to = new THREE.Vector3(d.settleX, d.radius, d.settleZ);
        m.position.lerpVectors(d.posFrom, to, e);
        m.position.y = d.radius + Math.abs(Math.sin(k * Math.PI)) * 0.25 * (1 - k);
        if (k >= 1 && !d.done) {
          d.done = true;
          if (this.sound) clack(0.4);
          if (d.spec.kept === false) {
            m.material.forEach((mat) => { mat.opacity = 0.35; });
          }
        }
      }
    }
    this.renderer.render(this.scene, this.camera);
    if (this.elapsed < T + 0.05) {
      requestAnimationFrame((t) => this.tick(t));
    } else {
      this.running = false;
      const cb = this.onDone;
      this.onDone = null;
      if (cb) cb();
    }
  }
}
