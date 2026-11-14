/* Ported from the Tech Drona website (tech drona/src/components/CourseScene.jsx, 2026-11-11) so LMS course
   cards show the same animated artwork. Keep the two in step. */
import type { CSSProperties, ReactElement } from "react";

/* Course card / course page artwork: one illustrated scene per course, each with its own idea, so every card
   says at a glance what the course builds. Animations are transform/opacity only (see .cs-* in global.css)
   and stop for reduced motion. viewBox 400 x 210. */

const NAVY = "#032269";
const LINE = "#dfe6f3";
const SANS = "'Plus Jakarta Sans', Inter, sans-serif";
const MONO = "ui-monospace, Consolas, monospace";

const Pill = ({ x, y, label, acc, dark = false, size = 9.4, w }: { x: number; y: number; label: string; acc: string; dark?: boolean; size?: number; w?: number }) => {
  const width = w || label.length * size * 0.6 + 26;
  return (
    <g>
      <rect x={x} y={y} width={width} height="22" rx="11" fill={dark ? NAVY : "#fff"} stroke={dark ? NAVY : LINE} />
      <circle cx={x + 11} cy={y + 11} r="3.4" fill={acc} />
      <text x={x + 19} y={y + 14.6} fontFamily={SANS} fontSize={size} fontWeight="700" fill={dark ? "#fff" : NAVY}>{label}</text>
    </g>
  );
};
const Bar = ({ x, y, w, h = 5, fill = "#cbd5e1", className, style }: { x: number; y: number; w: number; h?: number; fill?: string; className?: string; style?: CSSProperties }) => <rect className={className} style={style} x={x} y={y} width={w} height={h} rx={h / 2} fill={fill} />;
/* a dot that travels from (x1,y1) to (x2,y2) on a loop */
const Packet = ({ x1, y1, x2, y2, acc, delay = 0, dur = 2.4, r = 3.2 }: { x1: number; y1: number; x2: number; y2: number; acc: string; delay?: number; dur?: number; r?: number }) => (
  <circle className="cs-flow" cx={x1} cy={y1} r={r} fill={acc}
    style={{ "--dx": `${x2 - x1}px`, "--dy": `${y2 - y1}px`, animationDelay: `${delay}s`, animationDuration: `${dur}s` } as CSSProperties} />
);

/* ---------------- Python full stack: a laptop showing the web app, wired to a REST API and MySQL */
function Python({ acc }: { acc: string }) {
  return (
    <g>
      <rect x="56" y="30" width="196" height="128" rx="10" fill={NAVY} opacity=".08" transform="translate(4 5)" />
      <rect x="56" y="24" width="196" height="128" rx="10" fill={NAVY} />
      <rect x="63" y="31" width="182" height="112" rx="4" fill="#fff" />
      {/* the web app on screen */}
      <rect x="63" y="31" width="182" height="16" rx="4" fill="#f1f5fb" />
      <circle cx="73" cy="39" r="3.5" fill={acc} /><Bar x={81} y={37} w={30} h={4} fill={NAVY} />
      {[0, 1, 2].map((i) => <Bar key={i} x={170 + i * 22} y={37} w={16} h={4} />)}
      <Bar x={74} y={56} w={92} h={7} fill={NAVY} /><Bar x={74} y={68} w={70} />
      <rect className="cs-pulse" x="74" y="78" width="42" height="13" rx="6.5" fill={acc} />
      <text x="95" y="87.6" textAnchor="middle" fontFamily={SANS} fontSize="7" fontWeight="800" fill="#fff">Enroll</text>
      <rect x="178" y="54" width="56" height="38" rx="5" fill="#e7edf8" /><path d="M184 86 l12 -12 9 8 8 -6 15 10" fill="none" stroke={acc} strokeWidth="2" />
      {[0, 1, 2].map((i) => (
        <g key={i}>
          <rect x={74 + i * 57} y="100" width="50" height="34" rx="5" fill="#fff" stroke={LINE} />
          <rect x={78 + i * 57} y="104" width="42" height="12" rx="3" fill={i === 1 ? acc : "#e7edf8"} opacity={i === 1 ? 0.25 : 1} />
          <Bar x={78 + i * 57} y={121} w={30} h={4} fill="#94a3b8" /><Bar x={78 + i * 57} y={128} w={20} h={3} />
        </g>
      ))}
      <path d="M40 158 h228 l-12 10 h-204z" fill="#c9d4ec" /><rect x="138" y="158" width="32" height="4" rx="2" fill="#a9b8d8" />
      {/* REST API and database */}
      <g transform="translate(286 34)">
        <rect width="92" height="40" rx="10" fill="#fff" stroke={LINE} />
        <text x="12" y="17" fontFamily={MONO} fontSize="8.4" fill="#64748b">GET /courses</text>
        <rect x="12" y="23" width="38" height="12" rx="6" fill={acc} /><text x="31" y="31.6" textAnchor="middle" fontFamily={SANS} fontSize="7.4" fontWeight="800" fill="#fff">200 OK</text>
        <text x="58" y="32" fontFamily={SANS} fontSize="8" fontWeight="700" fill={NAVY}>Django</text>
      </g>
      <path d="M252 70 H286" stroke={acc} strokeWidth="1.6" strokeDasharray="3 3" />
      <Packet x1={252} y1={70} x2={286} y2={70} acc={acc} dur={1.6} />
      <g transform="translate(303 104)">
        <ellipse cx="29" cy="8" rx="29" ry="8" fill={NAVY} />
        <path d="M0 8 v40 a29 8 0 0 0 58 0 v-40 a29 8 0 0 1 -58 0z" fill="#0b3aa4" />
        <path d="M0 22 a29 8 0 0 0 58 0 M0 36 a29 8 0 0 0 58 0" fill="none" stroke="#fff" strokeOpacity=".22" />
        <text x="29" y="40" textAnchor="middle" fontFamily={SANS} fontSize="9" fontWeight="800" fill="#fff">MySQL</text>
      </g>
      <path d="M332 74 V104" stroke={NAVY} strokeOpacity=".3" strokeWidth="1.5" />
      <Packet x1={332} y1={104} x2={332} y2={74} acc={acc} delay={0.8} dur={1.6} />
    </g>
  );
}

/* ---------------- Java: a honeycomb of microservices around a gateway, and a cup of Java */
function Java({ acc }: { acc: string }) {
  const cx = 214, cy = 104, R = 66;
  const hex = (x: number, y: number, r: number) => Array.from({ length: 6 }, (_, i) => { const a = (Math.PI / 3) * i + Math.PI / 6; return `${(x + r * Math.cos(a)).toFixed(1)},${(y + r * Math.sin(a)).toFixed(1)}`; }).join(" ");
  const svcs = ["Users", "Orders", "Payments", "Stock", "Auth", "Notify"];
  return (
    <g>
      {svcs.map((s, i) => {
        const a = (Math.PI / 3) * i, x = cx + R * Math.cos(a), y = cy + R * 0.86 * Math.sin(a);
        return (
          <g key={s}>
            <path d={`M${cx} ${cy} L${x} ${y}`} stroke={NAVY} strokeOpacity=".18" strokeWidth="1.6" />
            <Packet x1={cx} y1={cy} x2={x} y2={y} acc={acc} delay={i * 0.45} dur={2.7} />
            <g className="cs-pulse" style={{ animationDelay: `${i * 0.45}s` }}>
              <polygon points={hex(x, y, 25)} fill="#fff" stroke={acc} strokeWidth="1.6" />
              <text x={x} y={y + 3.2} textAnchor="middle" fontFamily={SANS} fontSize="8.2" fontWeight="700" fill={NAVY}>{s}</text>
            </g>
          </g>
        );
      })}
      <polygon points={hex(cx, cy, 31)} fill={NAVY} />
      <text x={cx} y={cy - 2} textAnchor="middle" fontFamily={SANS} fontSize="8.4" fontWeight="800" fill="#fff">API</text>
      <text x={cx} y={cy + 9} textAnchor="middle" fontFamily={SANS} fontSize="8.4" fontWeight="800" fill="#fff">Gateway</text>
      {/* the cup of Java */}
      <g transform="translate(30 112)">
        {[0, 1, 2].map((i) => <path key={i} className="cs-steam" style={{ animationDelay: `${i * 0.6}s` }} d={`M${14 + i * 12} 18 q-6 -8 0 -16 q6 -8 0 -16`} fill="none" stroke={acc} strokeWidth="2.2" strokeLinecap="round" opacity=".6" />)}
        <path d="M4 24 h46 l-5 40 a8 8 0 0 1 -8 7 h-20 a8 8 0 0 1 -8 -7z" fill={acc} />
        <path d="M50 32 a11 11 0 0 1 0 22" fill="none" stroke={acc} strokeWidth="5" />
        <rect x="-2" y="72" width="60" height="6" rx="3" fill={NAVY} opacity=".2" />
      </g>
      <Pill x={300} y={14} label="Spring Boot" acc={acc} dark />
      <Pill x={318} y={176} label="Kafka" acc={acc} />
    </g>
  );
}

/* ---------------- MERN: the same app on the web and on a phone, React orbiting */
function Mern({ acc }: { acc: string }) {
  return (
    <g>
      {/* browser */}
      <rect x="26" y="34" width="196" height="132" rx="10" fill={NAVY} opacity=".07" transform="translate(4 5)" />
      <rect x="26" y="34" width="196" height="132" rx="10" fill="#fff" stroke={LINE} />
      <path d="M26 44 a10 10 0 0 1 10 -10 h176 a10 10 0 0 1 10 10 v8 h-196z" fill="#f1f5fb" />
      {["#ff6b6b", "#ffd166", "#4ade80"].map((c, i) => <circle key={c} cx={38 + i * 10} cy="43" r="3" fill={c} />)}
      <rect x="76" y="39" width="120" height="9" rx="4.5" fill="#fff" stroke={LINE} />
      <rect x="26" y="52" width="46" height="114" fill="#f6f8fc" />
      {[0, 1, 2, 3].map((i) => <Bar key={i} x={34} y={62 + i * 14} w={i ? 26 : 30} h={5} fill={i === 1 ? acc : "#cbd5e1"} />)}
      {[0, 1, 2, 3].map((i) => (
        <g key={i} className="cs-pop" style={{ animationDelay: `${i * 0.35}s` }}>
          <rect x={82 + (i % 2) * 68} y={60 + Math.floor(i / 2) * 50} width="60" height="42" rx="6" fill="#fff" stroke={LINE} />
          <rect x={88 + (i % 2) * 68} y={66 + Math.floor(i / 2) * 50} width="48" height="14" rx="3" fill={acc} opacity=".2" />
          <Bar x={88 + (i % 2) * 68} y={86 + Math.floor(i / 2) * 50} w={36} h={4} fill="#94a3b8" />
        </g>
      ))}
      {/* phone */}
      <rect x="244" y="26" width="84" height="164" rx="16" fill={NAVY} />
      <rect x="250" y="38" width="72" height="140" rx="6" fill="#fff" />
      <rect x="276" y="30" width="20" height="4" rx="2" fill="#1e3a8a" />
      {[0, 1, 2, 3].map((i) => (
        <g key={i} className="cs-slide" style={{ animationDelay: `${i * 0.3}s` }}>
          <circle cx="262" cy={56 + i * 26} r="7" fill={i === 0 ? acc : "#e7edf8"} />
          <Bar x={273} y={52 + i * 26} w={40} h={4} fill="#64748b" /><Bar x={273} y={59 + i * 26} w={28} h={3} />
        </g>
      ))}
      <rect x="250" y="160" width="72" height="18" fill="#f6f8fc" />
      {[0, 1, 2].map((i) => <circle key={i} cx={266 + i * 20} cy="169" r="3.5" fill={i === 0 ? acc : "#cbd5e1"} />)}
      {/* React orbit */}
      <g transform="translate(364 58)">
        {[0, 60, 120].map((d) => <ellipse key={d} rx="24" ry="9" fill="none" stroke={acc} strokeWidth="1.6" transform={`rotate(${d})`} />)}
        <circle r="4" fill={acc} />
        <g className="cs-spin"><circle cx="24" cy="0" r="2.6" fill={NAVY} /></g>
      </g>
      <Pill x={334} y={100} label="Node" acc={acc} size={8.6} />
      <Pill x={334} y={128} label="MongoDB" acc={acc} size={8.6} w={62} />
    </g>
  );
}

/* ---------------- MEAN: an Angular analytics dashboard with live charts */
function Mean({ acc }: { acc: string }) {
  const bars = [34, 52, 40, 64, 48, 72, 58];
  return (
    <g>
      <rect x="40" y="18" width="264" height="152" rx="10" fill={NAVY} />
      <rect x="47" y="25" width="250" height="138" rx="4" fill="#fff" />
      <rect x="153" y="170" width="38" height="16" fill="#c9d4ec" /><rect x="128" y="186" width="88" height="6" rx="3" fill="#a9b8d8" />
      <rect x="47" y="25" width="38" height="138" fill="#f6f8fc" />
      <rect x="55" y="33" width="22" height="8" rx="4" fill={acc} />
      {[0, 1, 2, 3].map((i) => <Bar key={i} x={55} y={52 + i * 14} w={22} h={4} />)}
      {[["1.2k", "Learners"], ["86%", "Completion"], ["24", "Live batches"]].map(([v, l], i) => (
        <g key={l}>
          <rect x={93 + i * 68} y="33" width="62" height="34" rx="6" fill="#fff" stroke={LINE} />
          <text x={100 + i * 68} y="50" fontFamily={SANS} fontSize="11" fontWeight="800" fill={i === 1 ? acc : NAVY}>{v}</text>
          <text x={100 + i * 68} y="61" fontFamily={SANS} fontSize="6.6" fill="#64748b">{l}</text>
        </g>
      ))}
      <rect x="93" y="74" width="198" height="82" rx="6" fill="#fff" stroke={LINE} />
      {bars.map((h, i) => <rect key={i} className="cs-grow" style={{ animationDelay: `${i * 0.12}s` }} x={104 + i * 26} y={150 - h} width="14" height={h} rx="3" fill={i === 5 ? acc : "#c9d4ec"} />)}
      {/* TypeScript shield */}
      <g transform="translate(320 30)">
        <path d="M30 0 l28 10 v22 c0 20 -12 32 -28 40 c-16 -8 -28 -20 -28 -40 v-22z" fill={acc} />
        <text x="30" y="44" textAnchor="middle" fontFamily={SANS} fontSize="17" fontWeight="800" fill="#fff">TS</text>
      </g>
      <Pill x={312} y={128} label="Angular" acc={acc} />
      <Pill x={312} y={156} label="RxJS" acc={acc} dark />
    </g>
  );
}

/* ---------------- Generative AI: a chat that generates an image */
function Genai({ acc }: { acc: string }) {
  return (
    <g>
      <rect x="22" y="22" width="192" height="168" rx="14" fill="#fff" stroke={LINE} />
      <rect x="64" y="34" width="138" height="26" rx="13" fill={acc} />
      <text x="133" y="51" textAnchor="middle" fontFamily={SANS} fontSize="9" fontWeight="700" fill="#fff">Design a course poster</text>
      <circle cx="40" cy="80" r="10" fill={NAVY} />
      <path d="M36 80 l3 -5 3 5 -3 5z" fill="#fff" />
      <rect x="56" y="70" width="140" height="58" rx="12" fill="#f4f1fe" />
      {[0, 1, 2].map((i) => <Bar key={i} className="cs-type" style={{ animationDelay: `${i * 0.5}s` }} x={66} y={82 + i * 12} w={[112, 96, 70][i] ?? 70} fill={i ? "#c4b5fd" : acc} />)}
      {[0, 1, 2].map((i) => <circle key={i} className="cs-dot" style={{ animationDelay: `${i * 0.2}s` }} cx={70 + i * 8} cy="120" r="2.4" fill={acc} />)}
      <rect x="32" y="150" width="172" height="28" rx="14" fill="#f6f8fc" stroke={LINE} />
      <Bar x={46} y={162} w={90} h={4} />
      <circle cx="188" cy="164" r="10" fill={acc} />
      <path d="M188 158 l1.6 4.4 4.4 1.6 -4.4 1.6 -1.6 4.4 -1.6 -4.4 -4.4 -1.6 4.4 -1.6z" fill="#fff" />
      {/* the generated image */}
      <g transform="translate(240 36)">
        <rect width="136" height="112" rx="12" fill={NAVY} opacity=".07" transform="translate(4 5)" />
        <rect width="136" height="112" rx="12" fill="#fff" stroke={LINE} />
        <rect x="8" y="8" width="120" height="96" rx="8" fill="#ede9fe" />
        <circle cx="100" cy="32" r="11" fill="#fbbf24" />
        <path d="M8 92 l36 -40 26 26 18 -16 40 30 v10 a8 8 0 0 1 -8 8 h-104 a8 8 0 0 1 -8 -8z" fill={acc} opacity=".85" />
        <path d="M8 98 l30 -24 30 18 30 -12 30 16 v6 a8 8 0 0 1 -8 8 h-104 a8 8 0 0 1 -8 -8z" fill={NAVY} opacity=".85" />
        <rect className="cs-reveal" x="8" y="8" width="120" height="96" rx="8" fill="#f4f1fe" />
      </g>
      {[[234, 28, 1], [384, 60, 0.8], [372, 160, 1.2], [246, 162, 0.7]].map(([x, y, s], i) => (
        <path key={i} className="cs-twinkle" style={{ animationDelay: `${i * 0.5}s` }} transform={`translate(${x} ${y}) scale(${s})`} d="M0 -8 l2 6 6 2 -6 2 -2 6 -2 -6 -6 -2 6 -2z" fill={i % 2 ? NAVY : acc} />
      ))}
      <Pill x={276} y={166} label="Generated" acc={acc} dark />
    </g>
  );
}

/* ---------------- Agentic AI: a robot agent using tools to work through a task list */
function Agentic({ acc }: { acc: string }) {
  const cx = 140, cy = 112, r = 74;
  const tools: [number, ReactElement][] = [
    [120, <g key="s"><circle cx="-2" cy="-2" r="6" fill="none" stroke={NAVY} strokeWidth="2.2" /><path d="M2.5 2.5 l5 5" stroke={NAVY} strokeWidth="2.4" strokeLinecap="round" /></g>],
    [170, <g key="d"><ellipse cx="0" cy="-6" rx="8" ry="3" fill={NAVY} /><path d="M-8 -6 v11 a8 3 0 0 0 16 0 v-11" fill={NAVY} /></g>],
    [220, <g key="m"><rect x="-9" y="-6" width="18" height="13" rx="2" fill="none" stroke={NAVY} strokeWidth="2" /><path d="M-8 -4 l8 6 8 -6" fill="none" stroke={NAVY} strokeWidth="2" /></g>],
    [270, <g key="c"><rect x="-8" y="-7" width="16" height="15" rx="2.5" fill="none" stroke={NAVY} strokeWidth="2" /><path d="M-8 -2 h16 M-4 -10 v5 M4 -10 v5" stroke={NAVY} strokeWidth="2" /></g>],
    [320, <g key="x"><path d="M-4 -6 l-6 6 6 6 M4 -6 l6 6 -6 6" fill="none" stroke={NAVY} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></g>],
  ];
  return (
    <g>
      {tools.map(([deg, icon], i) => {
        const a = (deg * Math.PI) / 180, x = cx + r * Math.cos(a), y = cy + r * 0.82 * Math.sin(a);
        return (
          <g key={deg}>
            <path d={`M${cx} ${cy} L${x} ${y}`} stroke={acc} strokeOpacity=".35" strokeWidth="1.6" strokeDasharray="3 4" />
            <Packet x1={cx} y1={cy} x2={x} y2={y} acc={acc} delay={i * 0.6} dur={3} />
            <circle cx={x} cy={y} r="17" fill="#fff" stroke={LINE} />
            <g transform={`translate(${x} ${y})`}>{icon}</g>
          </g>
        );
      })}
      {/* the robot */}
      <g className="cs-bob">
        <rect x={cx - 3} y={cy - 46} width="6" height="12" rx="3" fill={NAVY} />
        <circle className="cs-pulse" cx={cx} cy={cy - 48} r="5" fill={acc} />
        <rect x={cx - 28} y={cy - 34} width="56" height="44" rx="14" fill={NAVY} />
        <rect x={cx - 20} y={cy - 26} width="40" height="22" rx="8" fill="#1e3a8a" />
        <circle cx={cx - 9} cy={cy - 15} r="4.5" fill="#fff" /><circle cx={cx + 9} cy={cy - 15} r="4.5" fill="#fff" />
        <path d={`M${cx - 9} ${cy + 1} q9 6 18 0`} stroke={acc} strokeWidth="2.6" fill="none" strokeLinecap="round" />
        <rect x={cx - 20} y={cy + 14} width="40" height="22" rx="8" fill={NAVY} opacity=".85" />
      </g>
      {/* the task list it is working through */}
      <g transform="translate(262 34)">
        <rect width="120" height="138" rx="12" fill="#fff" stroke={LINE} />
        <text x="12" y="20" fontFamily={SANS} fontSize="9.4" fontWeight="800" fill={NAVY}>Task</text>
        {["Plan the steps", "Search the web", "Query data", "Draft the reply", "Send for review"].map((t, i) => (
          <g key={t} transform={`translate(12 ${34 + i * 21})`}>
            <rect width="14" height="14" rx="4" fill={i < 4 ? acc : "#fff"} stroke={i < 4 ? acc : "#cbd5e1"} className={i < 4 ? "cs-pop" : undefined} style={{ animationDelay: `${i * 0.5}s` }} />
            {i < 4 && <path d="M3.5 7.2 l2.6 2.6 4.6 -5" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" />}
            <text x="22" y="10.6" fontFamily={SANS} fontSize="8.4" fontWeight="600" fill={i < 4 ? NAVY : "#94a3b8"}>{t}</text>
          </g>
        ))}
      </g>
    </g>
  );
}

/* ---------------- AWS and DevOps: the DevOps infinity loop under the AWS cloud */
const LOOP = "M200 112 C 228 74, 318 70, 318 112 C 318 154, 228 150, 200 112 C 172 74, 82 70, 82 112 C 82 154, 172 150, 200 112 Z";
// reduced motion (or no browser, as when the brochures are rendered): the dot rests where the two loops meet
// LMS: rendered on the server, so the dot always travels (SMIL); CSS stops the other motion for reduced motion
const still = () => false;
function Aws({ acc }: { acc: string }) {
  // labels sit outside the loop's band so the travelling dot never runs over them
  const left = [["Plan", 128, 68], ["Code", 56, 115], ["Build", 100, 166], ["Test", 166, 166]];
  const right = [["Release", 262, 68], ["Deploy", 340, 90], ["Operate", 348, 134], ["Monitor", 268, 166]];
  return (
    <g>
      <g transform="translate(160 6)">
        <path d="M14 34 a16 16 0 0 1 4 -31 a22 22 0 0 1 40 -3 a16 16 0 0 1 24 12 a12 12 0 0 1 -2 22z" fill="#fff" stroke={LINE} strokeWidth="1.4" />
        <text x="47" y="25" textAnchor="middle" fontFamily={SANS} fontSize="11" fontWeight="800" fill={NAVY}>AWS</text>
      </g>
      <path d="M200 46 V72" stroke={acc} strokeWidth="1.5" strokeDasharray="3 3" />
      <path d={LOOP} fill="none" stroke="#e7edf8" strokeWidth="18" strokeLinejoin="round" />
      <path d="M200 112 C 172 74, 82 70, 82 112 C 82 154, 172 150, 200 112" fill="none" stroke={NAVY} strokeWidth="9" strokeLinecap="round" />
      <path d="M200 112 C 228 74, 318 70, 318 112 C 318 154, 228 150, 200 112" fill="none" stroke={acc} strokeWidth="9" strokeLinecap="round" />
      {/* SVG's own motion along the loop: CSS offset-path on SVG elements doesn't animate in Safari */}
      {still() ? <circle cx="200" cy="112" r="6" fill="#fff" stroke={NAVY} strokeWidth="2.4" /> : (
        <circle r="6" fill="#fff" stroke={NAVY} strokeWidth="2.4">
          <animateMotion dur="6s" repeatCount="indefinite" path={LOOP} />
        </circle>
      )}
      {[...left, ...right].map(([t, x, y], i) => (
        <text key={t} x={x} y={y} textAnchor="middle" fontFamily={SANS} fontSize="8.4" fontWeight="700" fill={i < 4 ? NAVY : "#7c4a03"}>{t}</text>
      ))}
      {([["Docker", 34], ["Kubernetes", 112], ["Terraform", 218], ["Jenkins", 306]] as [string, number][]).map(([t, x]) => <Pill key={t} x={x} y={180} label={t} acc={acc} size={8.6} />)}
    </g>
  );
}

const SCENES: Record<string, (p: { acc: string }) => ReactElement> = { "python-fullstack": Python, "java-fullstack": Java, mern: Mern, mean: Mean, genai: Genai, "agentic-ai": Agentic, "aws-devops": Aws };

/** Animated course artwork by scene id (the website course id, e.g. "python-fullstack"); null when unknown. */
export function CourseScene({ scene, accent, accentSoft, className = "" }: { scene?: string; accent: string; accentSoft: string; className?: string }) {
  const Scene = scene ? SCENES[scene] : undefined;
  if (!Scene) return null;
  const course = { theme: { accent, accentSoft } };
  return (
    <div className={`course-scene ${className}`} style={{ "--art-acc": course.theme.accent, "--art-soft": course.theme.accentSoft } as CSSProperties} aria-hidden="true">
      <svg viewBox="0 0 400 210" focusable="false">
        <Scene acc={course.theme.accent} />
      </svg>
    </div>
  );
}
