let score = 30;
let onReadyCb = null, onDoneCb = null, p = null, finished = false;

export function setScore(s) { if (typeof s === "number") score = s; }

export function startGame(hostId, readyCb) {
  onReadyCb = readyCb;
  finished = false;
  new p5((sketch) => {
    p = sketch;
    let particles = [];
    sketch.setup = () => {
      const c = sketch.createCanvas(sketch.windowWidth, sketch.windowHeight);
      c.parent(hostId);
      sketch.colorMode(sketch.RGB, 255);
      for (let i = 0; i < 300; i++) particles.push(newParticle());
      onReadyCb && onReadyCb();
      onReadyCb = null;
    };
    sketch.draw = () => {
      const calm = 1 - sketch.constrain(score / 100, 0, 1);
      sketch.background(10 + 40 * calm, 10 + 20 * calm, 30 + 30 * calm);
      for (const pt of particles) {
        pt.x += sketch.random(-1, 1) * (1 + 6 * (1 - calm));
        pt.y += sketch.random(-1, 1) * (1 + 6 * (1 - calm));
        sketch.noStroke();
        sketch.fill(200, 200, 255, 120);
        sketch.circle(pt.x, pt.y, pt.d);
      }
      drawOrb(sketch);
    };
  }, hostId);
}

function newParticle() {
  return { x: Math.random() * window.innerWidth,
           y: Math.random() * window.innerHeight,
           d: 2 + Math.random() * 4 };
}

function drawOrb(s) {
  const t = s.millis() / 1000;
  const phase = (t % 8) / 8;
  const grow = phase < 0.5 ? phase * 2 : (1 - phase) * 2;   // 4s in / 4s out
  const r = 60 + grow * 60;
  s.noStroke(); s.fill(120, 200, 255, 90);
  s.circle(s.width / 2, s.height / 2, r * 2);
  s.fill(235); s.textAlign(s.CENTER, s.CENTER); s.textSize(18);
  s.text(grow > 0.9 ? "breathe in" : "breathe out",
         s.width / 2, s.height / 2 + r + 24);
}

export function finishGame(doneCb) {
  onDoneCb = doneCb;
  if (!p || finished) { doneCb && doneCb(); return; }
  finished = true;
  p.noLoop();
  p.background(6, 40, 60);
  p.fill(235); p.textAlign(p.CENTER, p.CENTER); p.textSize(32);
  p.text("SYSTEM NOMINAL — RESUME MISSION", p.width / 2, p.height / 2);
  setTimeout(() => { p.remove(); p = null; onDoneCb && onDoneCb(); }, 2500);
}
