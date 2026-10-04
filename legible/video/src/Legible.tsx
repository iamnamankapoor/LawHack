import React, { useLayoutEffect, useRef, useState } from 'react';
import { AbsoluteFill, Easing, continueRender, delayRender, interpolate, useCurrentFrame } from 'remotion';

/* Same tokens as site/index.html */
const C = {
  paper: '#ffffff', ink: '#0a0a0a', grey: '#6f6f6f', soft: '#a3a3a3', hair: '#e6e6e6', wash: '#f4f4f4',
  cour: '#1a47ff', fond: '#ff5a1f', dem: '#e0006e', ok: '#0f8a3c', bad: '#e11d2e',
};
const FONT = '"Inter Tight", Inter, "Segoe UI", system-ui, sans-serif';
const EASE = Easing.bezier(0.2, 0.8, 0.2, 1);

// Inter Tight from Google Fonts, like the site. Frames wait until every weight is loaded.
if (typeof document !== 'undefined' && !document.getElementById('legible-font')) {
  const handle = delayRender('Loading Inter Tight', { timeoutInMilliseconds: 60000 });
  const link = document.createElement('link');
  link.id = 'legible-font';
  link.rel = 'stylesheet';
  link.href = 'https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&display=block';
  const done = () => continueRender(handle);
  link.onload = () => Promise.all([400, 500, 600, 700].map((w) => document.fonts.load(`${w} 40px "Inter Tight"`))).then(done, done);
  link.onerror = done;
  document.head.appendChild(link);
}

/** 0 → 1 between `start` and `start + dur` frames. */
const k = (f: number, start: number, dur = 18) =>
  interpolate(f, [start, start + dur], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: EASE });
const alpha = (hex: string, a: number) => hex + Math.round(Math.max(0, Math.min(1, a)) * 255).toString(16).padStart(2, '0');

/* Timeline (30 fps) */
const T = {
  introOut: 82, decision: 96, draft: 330, typeFrom: 362, check: 480, marks: 492, thread: 525, quash: 560,
  blocked: 595, fix: 660, fixed: 676, pass: 724, sent: 752, endOut: 790, end: 806,
};

/* The site's pictograms */
const PICS: Record<string, React.ReactNode> = {
  cour: (<><circle cx="12" cy="5" r="3" /><path d="M6 13.5c0-3 2.7-5 6-5s6 2 6 5V15H6z" /><rect x="2" y="15" width="20" height="7" /></>),
  fond: (<><circle cx="12" cy="6" r="3" /><path d="M6.5 14.5c0-2.8 2.5-4.6 5.5-4.6s5.5 1.8 5.5 4.6V16h-11z" /><rect x="5" y="16" width="14" height="6" /></>),
  dem: (<><circle cx="10" cy="5" r="3" /><path d="M5 22v-8.5C5 10.5 7.2 9 10 9c1.2 0 2.3.3 3.1.9L18 4l1.6 1.3-5.2 6.4c.4.6.6 1.2.6 1.8V22h-3.2v-6h-3.6v6z" /></>),
  person: (<><circle cx="12" cy="5" r="3" /><path d="M6.5 22v-8.5C6.5 10.5 9 9 12 9s5.5 1.5 5.5 4.5V22h-3.3v-6h-4.4v6z" /></>),
};
const Pic: React.FC<{ k: string; size: number; color: string }> = ({ k: key, size, color }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} style={{ fill: color, display: 'block' }}>{PICS[key]}</svg>
);

/* The three voices of Ass. plén., 22 Dec 2023, n° 20-20.648 (paraphrased from the French) */
const VOICES = [
  { id: 'dem', color: C.dem, name: 'The employer', role: 'Party, brings the appeal', para: '§ 4', line: 'The secret recording is admissible.', at: 104 },
  { id: 'fond', color: C.fond, name: 'Court of appeal', role: 'Judgment under review', para: '§ 13', line: 'Obtained unfairly, so the recordings are excluded.', at: 168 },
  { id: 'cour', color: C.cour, name: 'Cour de cassation', role: 'Decides', para: '§ 12', line: 'Unfair evidence is not automatically excluded. The judge must weigh it.', at: 232 },
];
const CARD = { top: 168, w: 500, gap: 70, left: 140 };

type Seg = { t: string; mark?: 'claim' | 'phrase' | 'fond' | 'cour' };
const OLD: Seg[] = [{ t: 'The Cour de cassation', mark: 'claim' }, { t: ' held that the recordings ' }, { t: 'must be excluded', mark: 'phrase' }, { t: '.' }];
const NEW: Seg[] = [{ t: 'The court of appeal', mark: 'fond' }, { t: ' excluded the recordings (§ 13); ' }, { t: 'the Cour de cassation', mark: 'cour' }, { t: ' quashed that ruling (§ 14).' }];
const OLD_LEN = OLD.reduce((n, s) => n + s.t.length, 0);

/** Underline (and optional wash) drawn left to right, so a mark reads as "pointed at", not decorated. */
const markStyle = (color: string, p: number, wash: boolean): React.CSSProperties => ({
  backgroundImage: `linear-gradient(${color}, ${color})${wash ? `, linear-gradient(${alpha(color, 0.16)}, ${alpha(color, 0.16)})` : ''}`,
  backgroundSize: `${p * 100}% 5px${wash ? `, ${p * 100}% 100%` : ''}`,
  backgroundPosition: `0 100%${wash ? ', 0 0' : ''}`,
  backgroundRepeat: 'no-repeat',
  WebkitBoxDecorationBreak: 'clone',
  boxDecorationBreak: 'clone',
});

const Tag: React.FC<{ color: string; children: React.ReactNode }> = ({ color, children }) => (
  <span style={{ background: color, color: C.paper, fontSize: 22, fontWeight: 700, letterSpacing: '0.08em', padding: '6px 12px' }}>{children}</span>
);

const Chips: React.FC<{ size?: number }> = ({ size = 22 }) => (
  <div style={{ display: 'flex', gap: 10 }}>
    {['Legora', 'Harvey', 'ChatGPT', 'Your own drafts'].map((n) => (
      <span key={n} style={{ border: `1.5px solid ${C.ink}`, padding: `${size * 0.22}px ${size * 0.55}px`, fontSize: size, fontWeight: 600 }}>{n}</span>
    ))}
  </div>
);

const pos = (el: HTMLElement | null, root: HTMLElement | null) => {
  let x = 0, y = 0;
  let e: HTMLElement | null = el;
  while (e && e !== root) { x += e.offsetLeft; y += e.offsetTop; e = e.offsetParent as HTMLElement | null; }
  return { x, y, w: el?.offsetWidth ?? 0, h: el?.offsetHeight ?? 0 };
};

export const Legible: React.FC = () => {
  const f = useCurrentFrame();
  const root = useRef<HTMLDivElement>(null);
  const phrase = useRef<HTMLSpanElement>(null);
  const fondCard = useRef<HTMLDivElement>(null);
  const [geo, setGeo] = useState<null | { x1: number; y1: number; x2: number; y2: number }>(null);

  // The thread joins the misattributed words to the voice that really said them; measured, not hard-coded.
  useLayoutEffect(() => {
    const p = pos(phrase.current, root.current), c = pos(fondCard.current, root.current);
    const g = { x1: p.x + p.w / 2, y1: p.y - 6, x2: c.x + c.w / 2, y2: c.y + c.h + 14 };
    if (!geo || Object.keys(g).some((key) => Math.abs((g as any)[key] - (geo as any)[key]) > 0.5)) setGeo(g);
  });

  const intro = k(f, 6, 22) * (1 - k(f, T.introOut, 14));
  const stage = k(f, T.decision, 12) * (1 - k(f, T.endOut, 16));
  const panelIn = k(f, T.draft, 22);
  const cardTop = interpolate(k(f, T.draft, 24), [0, 1], [330, CARD.top]);
  const typed = Math.floor(interpolate(f, [T.typeFrom, T.typeFrom + OLD_LEN], [0, OLD_LEN], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }));
  const oldOut = 1 - k(f, T.fix, 14);
  const marks = k(f, T.marks, 20) * oldOut;
  const thread = k(f, T.thread, 36) * oldOut;
  const fondFocus = k(f, T.thread + 10, 18) * oldOut;
  const quash = k(f, T.quash, 18);
  const blocked = k(f, T.blocked, 14) * oldOut;
  const fixedIn = k(f, T.fixed, 20);
  const fixedMarks = k(f, T.fixed + 22, 22);
  const pass = k(f, T.pass, 14);
  const sent = k(f, T.sent, 16);
  const dimOthers = 1 - 0.6 * k(f, T.check, 16);
  const endCard = k(f, T.end, 22);

  const steps: [number, number, string][] = [
    [T.decision, T.draft, 'In the decision'],
    [T.draft, T.check, 'A legal AI drafts the client note'],
    [T.check, T.fix, 'Legible checks who said it'],
    [T.fix, T.endOut, 'Fixed before it is sent'],
  ];
  const typing = f >= T.typeFrom && f < T.check;
  const caretOn = typing && (typed < OLD_LEN || Math.floor(f / 15) % 2 === 0);

  return (
    <AbsoluteFill ref={root} style={{ background: C.paper, color: C.ink, fontFamily: FONT, fontFeatureSettings: '"tnum" 1' }}>
      {/* Opening */}
      <div style={{ position: 'absolute', left: 140, right: 140, top: 380, opacity: intro, transform: `translateY(${(1 - k(f, 6, 22)) * 24 - k(f, T.introOut, 14) * 20}px)` }}>
        <div style={{ fontSize: 108, fontWeight: 600, letterSpacing: '-0.045em', lineHeight: 1 }}>A court decision has many voices.</div>
        <div style={{ marginTop: 34, fontSize: 46, color: C.grey, letterSpacing: '-0.02em', opacity: k(f, 26, 20) }}>Legal AI often mixes them up.</div>
      </div>

      {/* Persistent chrome */}
      <div style={{ position: 'absolute', left: 140, top: 64, fontSize: 32, fontWeight: 700, letterSpacing: '-0.04em', opacity: k(f, 0, 14) * (1 - k(f, T.endOut, 16)) }}>Legible</div>
      {steps.map(([a, b, label]) => (
        <div key={label} style={{ position: 'absolute', right: 140, top: 70, fontSize: 26, fontWeight: 600, color: C.grey, opacity: k(f, a, 14) * (1 - k(f, b - 4, 10)) }}>{label}</div>
      ))}
      <div style={{ position: 'absolute', left: 0, right: 0, top: 128, height: 1, background: C.hair, opacity: stage }} />

      <div style={{ opacity: stage }}>
        {/* The voices */}
        {VOICES.map((v, i) => {
          const a = k(f, v.at, 20), q = k(f, v.at + 14, 22);
          const isFond = v.id === 'fond', isCour = v.id === 'cour';
          const focus = isFond ? fondFocus : 0;
          return (
            <div key={v.id} ref={isFond ? fondCard : undefined}
              style={{ position: 'absolute', left: CARD.left + i * (CARD.w + CARD.gap), top: cardTop, width: CARD.w, padding: 26, boxSizing: 'border-box',
                outline: `3px solid ${alpha(v.color, focus)}`, background: alpha(v.color, 0.05 * focus),
                opacity: a * (isFond || isCour ? 1 : dimOthers), transform: `translateY(${(1 - a) * 24}px)` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
                <div style={{ width: 96, height: 96, background: alpha(v.color, 0.1), display: 'grid', placeItems: 'center', flex: 'none' }}>
                  <Pic k={v.id} size={60} color={v.color} />
                </div>
                <div>
                  <div style={{ fontSize: 34, fontWeight: 600, letterSpacing: '-0.02em' }}>{v.name}</div>
                  <div style={{ fontSize: 24, color: C.grey, marginTop: 2 }}>{v.role}</div>
                </div>
              </div>
              <div style={{ marginTop: 26, paddingTop: 20, borderTop: `3px solid ${v.color}`, opacity: q, transform: `translateY(${(1 - q) * 10}px)` }}>
                <div style={{ fontSize: 36, lineHeight: 1.22, fontWeight: 500, letterSpacing: '-0.02em', minHeight: 132 }}>{v.line}</div>
                <div style={{ marginTop: 14, fontSize: 24, fontWeight: 600, color: C.grey }}>{v.para}</div>
                {isCour && (
                  <div style={{ marginTop: 12, opacity: quash, transform: `translateY(${(1 - quash) * 8}px)` }}>
                    <span style={{ background: C.ink, color: C.paper, fontSize: 22, fontWeight: 600, padding: '6px 12px' }}>§ 14 · Quashes the court of appeal</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* The draft */}
        <div style={{ position: 'absolute', left: 140, top: 600, width: 1640, height: 360, boxSizing: 'border-box', border: `2px solid ${C.ink}`, background: C.paper,
          opacity: panelIn, transform: `translateY(${(1 - panelIn) * 40}px)` }}>
          <div style={{ position: 'absolute', inset: -2, border: `3px solid ${C.bad}`, opacity: blocked, pointerEvents: 'none' }} />
          <div style={{ position: 'absolute', inset: -2, border: `3px solid ${C.ok}`, opacity: pass, pointerEvents: 'none' }} />
          <div style={{ height: 72, borderBottom: `1.5px solid ${C.ink}`, display: 'flex', alignItems: 'center', gap: 20, padding: '0 40px' }}>
            <span style={{ fontSize: 26, fontWeight: 600 }}>Client note</span>
            <span style={{ fontSize: 24, color: C.grey }}>drafted by</span>
            <Chips />
          </div>
          <div style={{ position: 'relative', padding: '38px 44px 0' }}>
            {/* Original sentence (typed), then the fixed one in the same place */}
            <div style={{ fontSize: 48, lineHeight: 1.3, fontWeight: 500, letterSpacing: '-0.025em', opacity: oldOut }}>
              {(() => {
                let rem = typed, caretPlaced = false;
                return OLD.map((s, i) => {
                  const vis = Math.max(0, Math.min(s.t.length, rem)); rem -= s.t.length;
                  const caretHere = caretOn && !caretPlaced && (vis < s.t.length || i === OLD.length - 1);
                  if (caretHere) caretPlaced = true;
                  const st = s.mark === 'claim' ? markStyle(C.cour, marks, false) : s.mark === 'phrase' ? markStyle(C.fond, marks, true) : {};
                  return (
                    <span key={i} ref={s.mark === 'phrase' ? phrase : undefined} style={st}>
                      {s.t.slice(0, vis)}
                      {caretHere && <span style={{ display: 'inline-block', width: 4, height: '1em', background: C.ink, verticalAlign: '-0.12em', margin: '0 1px' }} />}
                      <span style={{ color: 'transparent' }}>{s.t.slice(vis)}</span>
                    </span>
                  );
                });
              })()}
            </div>
            <div style={{ position: 'absolute', left: 44, right: 44, top: 38, fontSize: 48, lineHeight: 1.3, fontWeight: 500, letterSpacing: '-0.025em',
              opacity: fixedIn, transform: `translateY(${(1 - fixedIn) * 12}px)` }}>
              {NEW.map((s, i) => (
                <span key={i} style={s.mark ? markStyle(s.mark === 'fond' ? C.fond : C.cour, fixedMarks, false) : {}}>{s.t}</span>
              ))}
            </div>
          </div>
          {/* Verdict row */}
          <div style={{ position: 'absolute', left: 44, right: 44, bottom: 34, height: 48 }}>
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', gap: 22, opacity: blocked }}>
              <Tag color={C.bad}>BLOCKED</Tag>
              <span style={{ fontSize: 32, fontWeight: 500, letterSpacing: '-0.015em' }}>This is the court of appeal (§ 13), and the Court quashed it (§ 14).</span>
            </div>
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', gap: 22, opacity: pass }}>
              <Tag color={C.ok}>PASS</Tag>
              <span style={{ fontSize: 32, fontWeight: 500, letterSpacing: '-0.015em' }}>Each statement matches its speaker.</span>
              <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14, opacity: sent, transform: `translateX(${(1 - sent) * 16}px)` }}>
                <span style={{ width: 14, height: 14, background: C.ok }} />
                <span style={{ fontSize: 30, fontWeight: 600, color: C.ok }}>Sent to client</span>
                <Pic k="person" size={44} color={C.ink} />
              </span>
            </div>
          </div>
        </div>

        {/* The thread */}
        {geo && (
          <svg width={1920} height={1080} style={{ position: 'absolute', left: 0, top: 0, pointerEvents: 'none', opacity: thread > 0 ? 1 : 0 }}>
            <path d={`M${geo.x1},${geo.y1} C${geo.x1},${(geo.y1 + geo.y2) / 2} ${geo.x2},${(geo.y1 + geo.y2) / 2} ${geo.x2},${geo.y2}`}
              pathLength={1} strokeDasharray={1} strokeDashoffset={1 - thread} fill="none" stroke={C.fond} strokeWidth={3} />
            <rect x={geo.x1 - 6} y={geo.y1 - 6} width={12} height={12} fill={C.fond} opacity={Math.min(1, thread * 4)} />
            <rect x={geo.x2 - 6} y={geo.y2 - 6} width={12} height={12} fill={C.fond} opacity={thread >= 0.98 ? 1 : 0} />
          </svg>
        )}

        <div style={{ position: 'absolute', left: 140, bottom: 52, fontSize: 22, color: C.grey }}>
          Cour de cassation, Assemblée plénière, 22 December 2023, n° 20-20.648 · paraphrased from the French
        </div>
      </div>

      {/* End card */}
      <div style={{ position: 'absolute', left: 140, right: 140, top: 300, opacity: endCard, transform: `translateY(${(1 - endCard) * 20}px)` }}>
        <div style={{ fontSize: 168, fontWeight: 700, letterSpacing: '-0.055em', lineHeight: 1 }}>Legible</div>
        <div style={{ marginTop: 30, fontSize: 52, fontWeight: 500, letterSpacing: '-0.025em' }}>Catches who-said-what errors before your client does.</div>
        <div style={{ marginTop: 70, display: 'flex', alignItems: 'center', gap: 26, opacity: k(f, T.end + 30, 20) }}>
          <span style={{ fontSize: 30, fontWeight: 600 }}>Works behind any legal AI</span>
          <Chips size={26} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
