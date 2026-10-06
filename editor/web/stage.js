// Deterministic stage: window.seek(t) draws the exact frame for time t (no real-time animation).
let TL = null, S = [], P = [], CAPS = [], W = 1080, H = 1920;
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const easeOutCubic = t => 1 - Math.pow(1 - t, 3);
const easeOutBack = t => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); };
const GRADES = {
  warm: "contrast(1.08) saturate(1.15) sepia(.10)",
  cool: "contrast(1.08) saturate(1.05) hue-rotate(-8deg)",
  punchy: "contrast(1.15) saturate(1.3)",
  none: "none",
};

function el(tag, cls, parent) { const e = document.createElement(tag); if (cls) e.className = cls; if (parent) parent.appendChild(e); return e; }

window.initStage = async function (tl) {
  TL = tl; W = tl.width; H = tl.height;
  const root = document.getElementById("root");
  root.style.width = W + "px"; root.style.height = H + "px";
  const th = tl.theme || {};
  root.style.setProperty("--text", th.text_color || "#fff");
  const family = th.font_family || "Inter, 'Segoe UI', Arial, sans-serif";
  if (th.font_file) {
    const st = document.createElement("style");
    st.textContent = `@font-face{font-family:'ChannelFont';src:url('${th.font_file}')}`;
    document.head.appendChild(st);
    root.style.fontFamily = `'ChannelFont', ${family}`;
    try { await document.fonts.load("900 40px ChannelFont"); } catch (e) {}
  } else root.style.fontFamily = family;

  const scenesEl = document.getElementById("scenes");
  const look = tl.look || {};
  scenesEl.style.filter = GRADES[look.grade || "none"] || "none";

  tl.scenes.forEach((sc, i) => {
    const d = el("div", "scene", scenesEl); d.style.zIndex = i + 1; d.style.display = "none";
    const bg = el("div", "bg", d);
    bg.style.background = `linear-gradient(160deg, ${sc.bg[0]}, ${sc.bg[1] || sc.bg[0]})`;
    const vis = el("div", "vis", d);
    let inner = null;
    if (sc.visual.type === "image") {
      inner = el("img", "", vis); inner.src = sc.visual.src; inner.style.objectFit = sc.visual.fit || "cover";
      const shade = el("div", "", d);
      shade.style.cssText = "position:absolute;inset:0;background:linear-gradient(to bottom,rgba(0,0,0,.18),rgba(0,0,0,0) 35%,rgba(0,0,0,.35))";
    } else if (sc.visual.type === "text") {
      inner = el("div", "ktext", vis);
      let txt = sc.visual.text || ""; if (th.uppercase) txt = txt.toUpperCase();
      inner.textContent = txt;
      const n = txt.length;
      inner.style.fontSize = Math.round(H * (n <= 20 ? 0.085 : n <= 50 ? 0.065 : 0.05)) + "px";
    }
    let ch = null;
    if (sc.character) {
      ch = el("div", "char", d);
      ch.style.height = Math.round(H * sc.character.scale) + "px";
      const im = el("img", "", ch); im.src = sc.character.src;
      ch.style[sc.character.side === "right" ? "right" : "left"] = Math.round(W * 0.03) + "px";
    }
    S.push({ sc, d, bg, vis, inner, ch });
  });

  const popEl = document.getElementById("popups");
  tl.scenes.forEach(sc => (sc.popups || []).forEach(p => {
    const e = el("div", "popup", popEl);
    let t = p.text; if (th.uppercase) t = t.toUpperCase();
    e.textContent = t; e.style.background = p.color || th.accent || "#FFD400";
    e.style.fontSize = Math.round(H * 0.062) + "px";
    e.style.top = ({ top: "20%", center: "46%", bottom: "68%" })[p.position] || "46%";
    P.push({ p, e });
  }));

  const caps = tl.captions || {};
  const capEl = document.getElementById("caps");
  const pos = caps.position || "lower";
  capEl.style[pos === "center" ? "top" : "bottom"] = pos === "center" ? "44%" : "24%";
  const fs = caps.size ? caps.size : Math.round(H * 0.058);
  capEl.style.fontSize = fs + "px";
  capEl.style.setProperty("--stroke", Math.round(fs * 0.11) + "px");
  (caps.chunks || []).forEach(c => {
    const box = el("div", "", capEl); box.style.display = "none"; box.style.position = "absolute"; box.style.left = "6%"; box.style.right = "6%";
    box.style.bottom = pos === "center" ? "auto" : "0";
    const spans = c.words.map(w => { const s = el("span", "cw", box); s.textContent = th.uppercase ? w.w.toUpperCase() : w.w; return { w, s }; });
    CAPS.push({ c, box, spans });
  });
  capEl.style.height = "0";

  const vig = document.getElementById("vig");
  if (look.vignette) vig.style.background = `radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(0,0,0,${look.vignette}) 100%)`;
  const gr = document.getElementById("grain");
  if (look.grain) {
    const svg = "<svg xmlns='http://www.w3.org/2000/svg' width='256' height='256'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(#n)'/></svg>";
    gr.style.backgroundImage = `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
    gr.style.opacity = look.grain; gr.style.mixBlendMode = "overlay";
  }
  const bars = document.getElementById("bars");
  if (look.letterbox) {
    const h = Math.round(H * look.letterbox);
    bars.innerHTML = `<div style="position:absolute;left:0;right:0;top:0;height:${h}px;background:#000"></div><div style="position:absolute;left:0;right:0;bottom:0;height:${h}px;background:#000"></div>`;
  }

  const imgs = [...document.images];
  await Promise.all(imgs.map(i => i.decode().catch(() => {})));
  await document.fonts.ready;
  window.seek(0);
};

function motion(m, p, lt) {
  switch (m) {
    case "zoom_in": return `scale(${1.04 + 0.16 * p})`;
    case "zoom_out": return `scale(${1.2 - 0.16 * p})`;
    case "pan_left": return `translateX(${(4 - 8 * p).toFixed(2)}%) scale(1.14)`;
    case "pan_right": return `translateX(${(-4 + 8 * p).toFixed(2)}%) scale(1.14)`;
    case "float": return `translateY(${(Math.sin(lt * 2) * 1.6).toFixed(2)}%) scale(1.08)`;
    case "push": return `scale(${1.02 + 0.2 * easeOutCubic(clamp(lt / 0.45))})`;
    case "shake": {
      const a = 22 * Math.exp(-lt * 3) + 3;
      return `translate(${(Math.sin(lt * 47) + Math.sin(lt * 31 + 1.3)) * a * 0.5}px, ${(Math.sin(lt * 53 + .7) + Math.sin(lt * 29)) * a * 0.5}px) scale(1.1)`;
    }
    default: return "none";
  }
}

window.seek = function (t) {
  S.forEach((o, i) => {
    const sc = o.sc, nxt = S[i + 1];
    const overlap = nxt ? nxt.sc.transition.dur : 0;
    const visible = t >= sc.start && t < sc.end + overlap;
    o.d.style.display = visible ? "block" : "none";
    if (!visible) return;
    const lt = t - sc.start, p = clamp(lt / Math.max(0.01, sc.end - sc.start));
    // entry transition
    const tr = sc.transition, e = tr.type === "cut" || i === 0 ? 1 : easeOutCubic(clamp(lt / tr.dur));
    let tf = "none", op = 1, fl = "none";
    if (e < 1) {
      if (tr.type === "fade") op = e;
      else if (tr.type === "whip") { tf = `translateX(${((1 - e) * 100).toFixed(2)}%)`; fl = `blur(${((1 - e) * 14).toFixed(1)}px)`; }
      else if (tr.type === "zoom") { tf = `scale(${1.35 - 0.35 * e})`; op = e; }
      else if (tr.type === "flash") { op = e; fl = `brightness(${1 + (1 - e) * 1.6})`; }
    }
    o.d.style.transform = tf; o.d.style.opacity = op; o.d.style.filter = fl;
    // visual motion
    if (o.inner) {
      if (sc.visual.type === "image") o.inner.style.transform = motion(sc.visual.motion, p, lt);
      else if (sc.visual.type === "text") {
        const k = easeOutBack(clamp(lt / 0.35));
        o.inner.style.transform = `scale(${0.7 + 0.3 * k}) translateY(${(Math.sin(lt * 1.6) * 0.8).toFixed(2)}%)`;
        o.inner.style.opacity = clamp(lt / 0.12);
      }
    }
    // gentle background drift for text/none scenes
    o.bg.style.transform = `scale(${1.05 + 0.04 * p}) translate(${(Math.sin(lt * 0.5) * 1.5).toFixed(2)}%, 0)`;
    if (o.ch) {
      const side = sc.character.side === "right" ? 1 : -1, act = sc.character.action;
      let ty = 0, tx = 0;
      if (act === "bounce") ty = -Math.abs(Math.sin(lt * 5)) * H * 0.012;
      const enter = easeOutCubic(clamp(lt / 0.45));
      if (act === "enter" || act === "bounce") tx = side * (1 - enter) * W * 0.5;
      o.ch.style.transform = `translate(${tx}px, ${ty}px) scale(${1 + Math.sin(lt * 2.2) * 0.012})`;
    }
  });

  P.forEach(({ p, e }) => {
    const lt = t - p.at;
    if (lt < 0 || lt > p.duration) { e.style.opacity = 0; return; }
    const inn = clamp(lt / 0.25), out = clamp((p.duration - lt) / 0.15);
    let tf;
    if (p.style === "slide") tf = `translate(-50%, ${-50 + (1 - easeOutCubic(inn)) * 60}%)`;
    else if (p.style === "stamp") tf = `translate(-50%,-50%) scale(${2.2 - 1.2 * easeOutCubic(clamp(lt / 0.18))}) rotate(-6deg)`;
    else tf = `translate(-50%,-50%) scale(${0.4 + 0.6 * easeOutBack(inn)})`;
    e.style.transform = tf; e.style.opacity = Math.min(1, inn * 3) * out;
  });

  const style = (TL.captions && TL.captions.style) || "karaoke";
  const accent = (TL.theme && TL.theme.accent) || "#FFD400";
  CAPS.forEach(({ c, box, spans }) => {
    const on = style !== "none" && t >= c.start && t < c.end;
    box.style.display = on ? "block" : "none";
    if (!on) return;
    const lt = t - c.start;
    box.style.transform = `scale(${0.85 + 0.15 * easeOutBack(clamp(lt / 0.14))})`;
    spans.forEach(({ w, s }) => {
      const active = t >= w.start && t < w.end;
      if (style === "karaoke") { s.style.color = active ? accent : "var(--text)"; s.style.transform = active ? "scale(1.12)" : "none"; }
      else if (style === "pop") { s.style.transform = active ? "scale(1.18)" : "none"; s.style.color = "var(--text)"; }
      else { s.style.color = "var(--text)"; s.style.transform = "none"; }
    });
  });

  const gr = document.getElementById("grain");
  if (gr.style.backgroundImage) {
    const f = Math.floor(t * TL.fps);
    gr.style.backgroundPosition = `${(f * 97) % 256}px ${(f * 61) % 256}px`;
  }
};
