'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

/* ------------------------------------------------------------------ */
/*  Real NEST trace format                                            */
/* ------------------------------------------------------------------ */
/*  Lines from nest/traces/*.jsonl look like:                          */
/*    {"ts":0.0,"agent":"a","kind":"start"}                            */
/*    {"ts":1.0,"agent":"a","kind":"send","to":"b",                   */
/*     "size":12,"msg":"hello","corr":"corr-1"}                       */
/*    {"ts":2.0,"agent":"b","kind":"receive","from":"a",              */
/*     "size":12,"msg":"hello","corr":"corr-1"}                       */
/*    {"ts":2.0,"agent":"b","kind":"dropped","from":"a",...}          */
/*    {"ts":3.0,"agent":"a","kind":"broadcast","msg":"...",           */
/*     "corr":"corr-2"}                                                */
/*    {"ts":10.0,"agent":"a","kind":"stop"}                            */

type TraceKind =
  | 'start'
  | 'stop'
  | 'send'
  | 'receive'
  | 'broadcast'
  | 'dropped';

interface TraceEvent {
  ts: number;
  agent: string;
  kind: TraceKind;
  from?: string;
  to?: string;
  msg?: string;
  size?: number;
  corr?: string;
}

/* ------------------------------------------------------------------ */
/*  Scenarios                                                          */
/* ------------------------------------------------------------------ */

interface ScenarioMeta {
  id: string;
  name: string;
  blurb: string;
  file: string;
}

const SCENARIOS: ScenarioMeta[] = [
  {
    id: 'auction',
    name: 'Auction',
    blurb: '1 auctioneer · 19 bidders · 5 rounds',
    file: '/traces/auction.jsonl',
  },
  {
    id: 'marketplace',
    name: 'Marketplace',
    blurb: '50 buyers · 50 sellers · matched trades',
    file: '/traces/marketplace.jsonl',
  },
  {
    id: 'marketplace2',
    name: 'Marketplace II',
    blurb: 'Same matcher, alternate run · 50×50',
    file: '/traces/marketplace2.jsonl',
  },
  {
    id: 'consensus',
    name: 'Consensus',
    blurb: '1 leader · 19 followers · paxos-style rounds',
    file: '/traces/consensus.jsonl',
  },
  {
    id: 'voting',
    name: 'Voting',
    blurb: '1 proposer · 1 coordinator · 18 voters',
    file: '/traces/voting.jsonl',
  },
  {
    id: 'reputation',
    name: 'Reputation',
    blurb: '16 honest · 4 malicious · 1 observer',
    file: '/traces/reputation.jsonl',
  },
  {
    id: 'supply_chain',
    name: 'Supply chain',
    blurb: 'supplier → manufacturer → distributor → retailer',
    file: '/traces/supply_chain.jsonl',
  },
  {
    id: 'shell_marketplace',
    name: 'Shell marketplace',
    blurb: '3 buyers · 3 sellers · shell-driven brains',
    file: '/traces/shell_marketplace.jsonl',
  },
];

/* ------------------------------------------------------------------ */
/*  Role palette                                                       */
/* ------------------------------------------------------------------ */

const ROLE_COLORS: Record<string, string> = {
  auctioneer:   '#C45A3C',
  bidder:       '#5C6E5A',
  leader:       '#C45A3C',
  follower:     '#5C6E5A',
  buyer:        '#C45A3C',
  seller:       '#221F1A',
  proposer:     '#C45A3C',
  coordinator:  '#B58432',
  voter:        '#5C6E5A',
  honest:       '#5C6E5A',
  malicious:    '#C45A3C',
  observer:     '#8C8576',
  supplier:     '#B58432',
  manufacturer: '#C45A3C',
  distributor:  '#5C6E5A',
  retailer:     '#221F1A',
};

function roleOf(agent: string): string {
  return agent.replace(/-\d+$/, '');
}

function roleColor(role: string): string {
  return ROLE_COLORS[role] ?? '#6B6557';
}

/* ------------------------------------------------------------------ */
/*  Role icons — line-art, no background, drawn in the nest aesthetic */
/* ------------------------------------------------------------------ */
/*  Each path is laid out in a 24×24 viewBox, centered around (12,12),*/
/*  stroke-only so it sits flush against the cream backdrop.          */

interface RoleIconProps {
  role: string;
  cx: number;
  cy: number;
  size: number;
  color: string;
  strokeWidth?: number;
}

function RoleIcon({
  role,
  cx,
  cy,
  size,
  color,
  strokeWidth = 1.4,
}: RoleIconProps) {
  const half = size / 2;
  const s = size / 24;
  // We translate so the (0,0) corner of a 24×24 box sits at (cx-half, cy-half).
  const tx = cx - half;
  const ty = cy - half;
  const common = {
    stroke: color,
    fill: 'none' as const,
    strokeWidth: strokeWidth / s,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };
  return (
    <g transform={`translate(${tx},${ty}) scale(${s})`}>
      {(() => {
        switch (role) {
          case 'auctioneer':
            // gavel: diamond head + handle + base
            return (
              <>
                <path d="M5 13 L11 7 L17 13 L11 19 Z" {...common} />
                <path d="M13 7 L20 2" {...common} />
                <path d="M3 21 L21 21" {...common} />
              </>
            );
          case 'bidder':
            // raised paddle
            return (
              <>
                <path d="M7 4 H17 V13 H7 Z" {...common} />
                <path d="M12 13 V22" {...common} />
              </>
            );
          case 'leader':
            // crown
            return (
              <>
                <path
                  d="M3 8 L7 14 L12 5 L17 14 L21 8 L20 19 H4 Z"
                  {...common}
                />
                <path d="M3 21 H21" {...common} />
              </>
            );
          case 'follower':
            // small person — head + body V
            return (
              <>
                <circle cx={12} cy={7} r={2.8} {...common} />
                <path d="M6 21 L12 12 L18 21" {...common} />
              </>
            );
          case 'buyer':
            // shopping bag
            return (
              <>
                <path d="M5 8 L7 22 H17 L19 8 Z" {...common} />
                <path d="M9 8 V5.5 a3 3 0 0 1 6 0 V8" {...common} />
              </>
            );
          case 'seller':
            // coin stack
            return (
              <>
                <ellipse cx={12} cy={7} rx={7} ry={2.4} {...common} />
                <path d="M5 7 V12" {...common} />
                <path d="M19 7 V12" {...common} />
                <ellipse cx={12} cy={12} rx={7} ry={2.4} {...common} />
                <path d="M5 12 V17" {...common} />
                <path d="M19 12 V17" {...common} />
                <ellipse cx={12} cy={17} rx={7} ry={2.4} {...common} />
              </>
            );
          case 'proposer':
            // speech bubble with tail
            return (
              <>
                <path d="M4 4 H20 V15 H11 L5 21 V15 H4 Z" {...common} />
                <path d="M8 9 H16" {...common} />
                <path d="M8 12 H14" {...common} />
              </>
            );
          case 'coordinator':
            // hub with radiating ties (like a coordinator node)
            return (
              <>
                <circle cx={12} cy={12} r={3.2} {...common} />
                <path d="M12 2 V6" {...common} />
                <path d="M12 18 V22" {...common} />
                <path d="M2 12 H6" {...common} />
                <path d="M18 12 H22" {...common} />
                <path d="M5 5 L8 8" {...common} />
                <path d="M19 5 L16 8" {...common} />
                <path d="M5 19 L8 16" {...common} />
                <path d="M19 19 L16 16" {...common} />
              </>
            );
          case 'voter':
            // ballot with check
            return (
              <>
                <path d="M4 4 H20 V20 H4 Z" {...common} />
                <path d="M8 12 L11 15 L17 9" {...common} />
              </>
            );
          case 'honest':
            // shield with check
            return (
              <>
                <path
                  d="M12 3 L20 6 V12 C20 17 16 20 12 21 C8 20 4 17 4 12 V6 Z"
                  {...common}
                />
                <path d="M8 12 L11 15 L16 9" {...common} />
              </>
            );
          case 'malicious':
            // jagged lightning
            return (
              <path
                d="M13 2 L5 13 L11 13 L8 22 L19 10 L13 10 L16 2 Z"
                {...common}
              />
            );
          case 'observer':
            // eye
            return (
              <>
                <path d="M2 12 Q12 4 22 12 Q12 20 2 12 Z" {...common} />
                <circle cx={12} cy={12} r={3.4} {...common} />
                <circle cx={12} cy={12} r={1} fill={color} stroke="none" />
              </>
            );
          case 'supplier':
            // crate
            return (
              <>
                <path d="M4 6 H20 V20 H4 Z" {...common} />
                <path d="M4 13 H20" {...common} />
                <path d="M12 6 V20" {...common} />
              </>
            );
          case 'manufacturer':
            // gear
            return (
              <>
                <circle cx={12} cy={12} r={5} {...common} />
                <circle cx={12} cy={12} r={1.6} {...common} />
                {[0, 45, 90, 135, 180, 225, 270, 315].map((deg) => {
                  const rad = (deg * Math.PI) / 180;
                  const x1 = 12 + Math.cos(rad) * 6;
                  const y1 = 12 + Math.sin(rad) * 6;
                  const x2 = 12 + Math.cos(rad) * 9;
                  const y2 = 12 + Math.sin(rad) * 9;
                  return (
                    <path
                      key={deg}
                      d={`M${x1} ${y1} L${x2} ${y2}`}
                      {...common}
                    />
                  );
                })}
              </>
            );
          case 'distributor':
            // small truck
            return (
              <>
                <path d="M2 9 H13 V17 H2 Z" {...common} />
                <path d="M13 12 H18 L21 15 V17 H13 Z" {...common} />
                <circle cx={6} cy={19} r={1.6} {...common} />
                <circle cx={17} cy={19} r={1.6} {...common} />
              </>
            );
          case 'retailer':
            // storefront / house
            return (
              <>
                <path d="M3 12 L12 4 L21 12 V21 H3 Z" {...common} />
                <path d="M10 21 V14 H14 V21" {...common} />
              </>
            );
          default:
            // generic: small nest mark — three crossed twigs in a ring
            return (
              <>
                <ellipse cx={12} cy={13} rx={8.5} ry={5} {...common} />
                <path d="M5 13 L19 12" {...common} />
                <path d="M7 9 L17 17" {...common} />
                <path d="M7 17 L17 9" {...common} />
              </>
            );
        }
      })()}
    </g>
  );
}

/* ------------------------------------------------------------------ */
/*  Trace parser                                                       */
/* ------------------------------------------------------------------ */

function parseTrace(text: string): TraceEvent[] {
  const out: TraceEvent[] = [];
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    try {
      const obj = JSON.parse(line);
      if (typeof obj.ts === 'number' && typeof obj.kind === 'string' && obj.agent) {
        out.push(obj as TraceEvent);
      }
    } catch {
      /* skip */
    }
  }
  out.sort((a, b) => a.ts - b.ts);
  return out;
}

/* ------------------------------------------------------------------ */
/*  Derived structures                                                 */
/* ------------------------------------------------------------------ */

interface Agent {
  id: string;
  role: string;
}

interface Flight {
  source: string;
  target: string;
  tStart: number;
  tEnd: number;
  kind: 'send' | 'broadcast' | 'dropped';
  msg: string;
}

interface EdgeKey {
  source: string;
  target: string;
  count: number;
}

interface Derived {
  agents: Agent[];
  agentIndex: Map<string, number>;
  flights: Flight[];
  edges: EdgeKey[];
  tMin: number;
  tMax: number;
  totalSent: number;
  totalReceived: number;
  totalDropped: number;
  totalBroadcasts: number;
}

function derive(events: TraceEvent[]): Derived {
  const agents = new Map<string, Agent>();
  const ensureAgent = (id: string) => {
    if (!agents.has(id)) agents.set(id, { id, role: roleOf(id) });
  };

  // pending sends keyed by corr -> {from, to, ts, msg}
  type Pending = { from: string; to?: string; ts: number; msg: string; kind: 'send' | 'broadcast' };
  const pending = new Map<string, Pending>();
  const flights: Flight[] = [];

  let totalSent = 0;
  let totalReceived = 0;
  let totalDropped = 0;
  let totalBroadcasts = 0;

  let tMin = Infinity;
  let tMax = -Infinity;

  for (const e of events) {
    if (e.ts < tMin) tMin = e.ts;
    if (e.ts > tMax) tMax = e.ts;
    ensureAgent(e.agent);
    if (e.from) ensureAgent(e.from);
    if (e.to) ensureAgent(e.to);

    if (e.kind === 'send' && e.to && e.corr) {
      pending.set(e.corr, {
        from: e.agent,
        to: e.to,
        ts: e.ts,
        msg: e.msg ?? '',
        kind: 'send',
      });
      totalSent++;
    } else if (e.kind === 'broadcast' && e.corr) {
      pending.set(e.corr, {
        from: e.agent,
        ts: e.ts,
        msg: e.msg ?? '',
        kind: 'broadcast',
      });
      totalBroadcasts++;
    } else if (e.kind === 'receive' && e.corr && e.from) {
      const p = pending.get(e.corr);
      if (p) {
        flights.push({
          source: p.from,
          target: e.agent,
          tStart: p.ts,
          tEnd: e.ts,
          kind: p.kind,
          msg: p.msg,
        });
        if (p.kind === 'send') pending.delete(e.corr);
        // broadcasts may fan out to many receivers, so keep pending entry
      } else {
        // Receive without recorded send (e.g. trace cut short). Use a small synthetic flight.
        flights.push({
          source: e.from,
          target: e.agent,
          tStart: Math.max(tMin, e.ts - 1),
          tEnd: e.ts,
          kind: 'send',
          msg: e.msg ?? '',
        });
      }
      totalReceived++;
    } else if (e.kind === 'dropped' && e.from && e.corr) {
      const p = pending.get(e.corr);
      if (p && p.to) {
        flights.push({
          source: p.from,
          target: p.to,
          tStart: p.ts,
          tEnd: e.ts,
          kind: 'dropped',
          msg: p.msg,
        });
        pending.delete(e.corr);
      }
      totalDropped++;
    }
  }

  // Any pending sends that never delivered: treat as dropped at tMax.
  for (const [, p] of pending) {
    if (p.kind === 'send' && p.to) {
      flights.push({
        source: p.from,
        target: p.to,
        tStart: p.ts,
        tEnd: Math.max(p.ts + 1, tMax),
        kind: 'dropped',
        msg: p.msg,
      });
    }
  }

  const agentList = Array.from(agents.values());
  const agentIndex = new Map(agentList.map((a, i) => [a.id, i]));

  // Aggregate edge counts (directed)
  const edgeMap = new Map<string, number>();
  for (const f of flights) {
    const key = `${f.source} ${f.target}`;
    edgeMap.set(key, (edgeMap.get(key) ?? 0) + 1);
  }
  const edges: EdgeKey[] = [];
  for (const [key, count] of edgeMap) {
    const [source, target] = key.split(' ');
    edges.push({ source, target, count });
  }

  return {
    agents: agentList,
    agentIndex,
    flights,
    edges,
    tMin: isFinite(tMin) ? tMin : 0,
    tMax: isFinite(tMax) ? tMax : 1,
    totalSent,
    totalReceived,
    totalDropped,
    totalBroadcasts,
  };
}

/* ------------------------------------------------------------------ */
/*  Layout: role-aware, deterministic                                 */
/* ------------------------------------------------------------------ */

interface Pos {
  x: number;
  y: number;
}

function computeLayout(agents: Agent[], width: number, height: number): Map<string, Pos> {
  const positions = new Map<string, Pos>();
  const cx = width / 2;
  const cy = height / 2;

  // Group by role, preserve numeric order within role
  const byRole = new Map<string, Agent[]>();
  for (const a of agents) {
    if (!byRole.has(a.role)) byRole.set(a.role, []);
    byRole.get(a.role)!.push(a);
  }
  for (const list of byRole.values()) {
    list.sort((a, b) => {
      const an = parseInt(a.id.split('-').pop() ?? '0', 10) || 0;
      const bn = parseInt(b.id.split('-').pop() ?? '0', 10) || 0;
      return an - bn;
    });
  }

  const roles = Array.from(byRole.keys());
  const roleCounts = roles.map((r) => byRole.get(r)!.length);
  const minDim = Math.min(width, height);

  // Heuristic 1: pure chain (each role count is 1, ≤6 roles)
  if (roles.length >= 2 && roles.length <= 6 && roleCounts.every((c) => c === 1)) {
    const padding = minDim * 0.18;
    const usable = width - padding * 2;
    roles.forEach((r, i) => {
      const a = byRole.get(r)![0];
      const x = padding + (usable * i) / Math.max(1, roles.length - 1);
      positions.set(a.id, { x, y: cy });
    });
    return positions;
  }

  // Heuristic 2: hub-and-spoke — one role of size 1, one large role
  const singletonRoles = roles.filter((r) => byRole.get(r)!.length === 1);
  const largeRoles = roles.filter((r) => byRole.get(r)!.length >= 4);
  if (
    singletonRoles.length >= 1 &&
    largeRoles.length === 1 &&
    singletonRoles.length + largeRoles.length === roles.length
  ) {
    // Singleton(s) in center (stacked vertically if >1), large role in outer ring
    const ring = byRole.get(largeRoles[0])!;
    const ringRadius = minDim * 0.4;
    ring.forEach((a, i) => {
      const angle = (2 * Math.PI * i) / ring.length - Math.PI / 2;
      positions.set(a.id, {
        x: cx + ringRadius * Math.cos(angle),
        y: cy + ringRadius * Math.sin(angle),
      });
    });
    singletonRoles.forEach((r, i) => {
      const a = byRole.get(r)![0];
      const offsetY = (i - (singletonRoles.length - 1) / 2) * minDim * 0.08;
      positions.set(a.id, { x: cx, y: cy + offsetY });
    });
    return positions;
  }

  // Heuristic 3: two large roles facing each other (marketplace: 50 buyers vs 50 sellers)
  if (roles.length === 2 && roleCounts.every((c) => c >= 4)) {
    const [rA, rB] = roles;
    const listA = byRole.get(rA)!;
    const listB = byRole.get(rB)!;
    const colA = width * 0.22;
    const colB = width * 0.78;
    const ySpanA = height * 0.78;
    const ySpanB = height * 0.78;
    const yA0 = (height - ySpanA) / 2;
    const yB0 = (height - ySpanB) / 2;
    listA.forEach((a, i) => {
      positions.set(a.id, {
        x: colA,
        y: yA0 + (ySpanA * (i + 0.5)) / listA.length,
      });
    });
    listB.forEach((b, i) => {
      positions.set(b.id, {
        x: colB,
        y: yB0 + (ySpanB * (i + 0.5)) / listB.length,
      });
    });
    return positions;
  }

  // Default: cluster by role on outer circle, with each role packed into its own
  // small disc.
  const ringRadius = minDim * 0.34;
  const clusterRadius = (minDim * 0.32) / Math.max(2, roles.length);
  roles.forEach((r, ri) => {
    const list = byRole.get(r)!;
    const baseAngle = (2 * Math.PI * ri) / roles.length - Math.PI / 2;
    const baseX = cx + ringRadius * Math.cos(baseAngle);
    const baseY = cy + ringRadius * Math.sin(baseAngle);
    list.forEach((a, i) => {
      const inner = (2 * Math.PI * i) / Math.max(1, list.length);
      const r2 = list.length === 1 ? 0 : clusterRadius;
      positions.set(a.id, {
        x: baseX + r2 * Math.cos(inner),
        y: baseY + r2 * Math.sin(inner),
      });
    });
  });
  return positions;
}

/* ------------------------------------------------------------------ */
/*  Player                                                             */
/* ------------------------------------------------------------------ */

interface PlayerProps {
  derived: Derived;
}

function Player({ derived }: PlayerProps) {
  // Sim time = the timestamp in trace seconds we are currently "at".
  // Player is keyed on scenarioId by parent, so this remounts on scenario
  // change and we get a fresh tMin without a reset effect.
  const [simTime, setSimTime] = useState(derived.tMin);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [hover, setHover] = useState<string | null>(null);

  // SVG viewport — fixed coordinate system, scales with container.
  const W = 800;
  const H = 560;

  const positions = useMemo(
    () => computeLayout(derived.agents, W, H),
    [derived.agents],
  );

  // Animation loop: sim seconds per wall second derived from total duration.
  // We compress the whole trace into ~18 seconds of real time at 1×.
  const targetDuration = 18;
  const simPerWallSec =
    Math.max(derived.tMax - derived.tMin, 0.01) / targetDuration;

  const lastWall = useRef<number | null>(null);
  useEffect(() => {
    if (!playing) {
      lastWall.current = null;
      return;
    }
    let frame: number;
    const tick = (now: number) => {
      if (lastWall.current === null) lastWall.current = now;
      const dtMs = now - lastWall.current;
      lastWall.current = now;
      setSimTime((t) => {
        const next = t + (dtMs / 1000) * simPerWallSec * speed;
        if (next >= derived.tMax) {
          setPlaying(false);
          return derived.tMax;
        }
        return next;
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, speed, simPerWallSec, derived.tMax]);

  // In-flight messages at current sim time
  interface InFlight {
    source: string;
    target: string;
    kind: 'send' | 'broadcast' | 'dropped';
    progress: number;
    msg: string;
  }
  const inFlight: InFlight[] = useMemo(() => {
    const t = simTime;
    const out: InFlight[] = [];
    for (const f of derived.flights) {
      if (t < f.tStart) continue;
      // Show in-flight for the lifetime of the message; brief tail after arrival.
      const tail = Math.max((f.tEnd - f.tStart) * 0.05, 0.5);
      if (t > f.tEnd + tail) continue;
      const dur = Math.max(f.tEnd - f.tStart, 1e-6);
      let p = (t - f.tStart) / dur;
      if (p > 1) p = 1;
      out.push({
        source: f.source,
        target: f.target,
        kind: f.kind,
        progress: p,
        msg: f.msg,
      });
      if (out.length > 800) break;
    }
    return out;
  }, [simTime, derived.flights]);

  // Active agents (any flight involving them currently in flight or recently)
  const activeAgents = useMemo(() => {
    const s = new Set<string>();
    for (const f of inFlight) {
      s.add(f.source);
      s.add(f.target);
    }
    return s;
  }, [inFlight]);

  // Edge weights derived from messages roughly near current time (windowed)
  const window = (derived.tMax - derived.tMin) * 0.05;
  const recentEdges = useMemo(() => {
    const m = new Map<string, number>();
    for (const f of derived.flights) {
      if (f.tEnd < simTime - window) continue;
      if (f.tStart > simTime) continue;
      const key = `${f.source} ${f.target}`;
      m.set(key, (m.get(key) ?? 0) + 1);
    }
    return m;
  }, [simTime, derived.flights, window]);

  const maxRecent = Math.max(1, ...recentEdges.values());

  // Aggregate counters as of current sim time
  const counters = useMemo(() => {
    let sent = 0;
    let received = 0;
    let dropped = 0;
    for (const f of derived.flights) {
      if (f.tStart <= simTime) {
        if (f.kind === 'dropped') {
          if (f.tEnd <= simTime) dropped++;
        } else {
          sent++;
          if (f.tEnd <= simTime) received++;
        }
      }
    }
    return { sent, received, dropped, inFlight: inFlight.length };
  }, [simTime, derived.flights, inFlight.length]);

  const pct = ((simTime - derived.tMin) / Math.max(derived.tMax - derived.tMin, 1e-6)) * 100;

  // Hover edges — neighbors of hovered agent
  const neighborSet = useMemo(() => {
    if (!hover) return new Set<string>();
    const s = new Set<string>();
    for (const e of derived.edges) {
      if (e.source === hover) s.add(e.target);
      if (e.target === hover) s.add(e.source);
    }
    return s;
  }, [hover, derived.edges]);

  const fmt = (t: number) => t.toFixed(2);

  return (
    <div className="space-y-6">
      {/* Stage */}
      <div className="relative rounded-2xl border border-cream-400/70 bg-cream-50 overflow-hidden">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="xMidYMid meet"
          className="block w-full"
          style={{ aspectRatio: `${W} / ${H}` }}
        >
          <defs>
            <radialGradient id="msg-glow-send" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#C45A3C" stopOpacity="0.9" />
              <stop offset="100%" stopColor="#C45A3C" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="msg-glow-broadcast" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#B58432" stopOpacity="0.9" />
              <stop offset="100%" stopColor="#B58432" stopOpacity="0" />
            </radialGradient>
            <radialGradient id="msg-glow-dropped" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#8C8576" stopOpacity="0.9" />
              <stop offset="100%" stopColor="#8C8576" stopOpacity="0" />
            </radialGradient>
          </defs>

          {/* Static edges — only ones with traffic in current window */}
          {derived.edges.map((e) => {
            const p1 = positions.get(e.source);
            const p2 = positions.get(e.target);
            if (!p1 || !p2) return null;
            const key = `${e.source} ${e.target}`;
            const recent = recentEdges.get(key) ?? 0;
            if (recent === 0 && hover === null) return null;
            const isHovered =
              hover &&
              (e.source === hover || e.target === hover);
            const intensity = recent / maxRecent;
            const opacity = isHovered ? 0.45 : 0.06 + intensity * 0.22;
            const thickness = isHovered ? 1.5 : 0.6 + intensity * 1.4;
            return (
              <line
                key={key}
                x1={p1.x}
                y1={p1.y}
                x2={p2.x}
                y2={p2.y}
                stroke={isHovered ? '#C45A3C' : '#221F1A'}
                strokeWidth={thickness}
                strokeOpacity={opacity}
                strokeLinecap="round"
              />
            );
          })}

          {/* In-flight messages — small twig segments oriented along travel */}
          {inFlight.map((f, i) => {
            const p1 = positions.get(f.source);
            const p2 = positions.get(f.target);
            if (!p1 || !p2) return null;
            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            const len = Math.hypot(dx, dy) || 1;
            const ux = dx / len;
            const uy = dy / len;
            const cxp = p1.x + dx * f.progress;
            const cyp = p1.y + dy * f.progress;
            const twigLen = 9;
            const x1 = cxp - ux * twigLen * 0.5;
            const y1 = cyp - uy * twigLen * 0.5;
            const x2 = cxp + ux * twigLen * 0.5;
            const y2 = cyp + uy * twigLen * 0.5;
            const stroke =
              f.kind === 'dropped'
                ? '#8C8576'
                : f.kind === 'broadcast'
                ? '#B58432'
                : '#C45A3C';
            const fade =
              f.progress >= 1
                ? Math.max(0, 1 - (f.progress - 1) * 4)
                : 0.4 + f.progress * 0.6;
            return (
              <g key={i} style={{ opacity: fade }}>
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={stroke}
                  strokeWidth={2.4}
                  strokeLinecap="round"
                />
                <circle cx={x2} cy={y2} r={1.8} fill={stroke} />
              </g>
            );
          })}

          {/* Agent nodes — line-art icons, no background */}
          {derived.agents.map((a) => {
            const pos = positions.get(a.id);
            if (!pos) return null;
            const active = activeAgents.has(a.id);
            const dimmed = hover && hover !== a.id && !neighborSet.has(a.id);
            const dense = derived.agents.length > 30;
            const baseSize = dense ? 16 : 24;
            const size =
              hover === a.id
                ? baseSize + 6
                : active
                ? baseSize + 2
                : baseSize;
            const color = roleColor(a.role);
            const hitRadius = size * 0.7;
            return (
              <g
                key={a.id}
                onMouseEnter={() => setHover(a.id)}
                onMouseLeave={() => setHover(null)}
                style={{
                  cursor: 'pointer',
                  opacity: dimmed ? 0.22 : 1,
                  transition: 'opacity 0.2s ease',
                }}
              >
                {active && (
                  <circle
                    cx={pos.x}
                    cy={pos.y}
                    r={size * 0.65}
                    fill={color}
                    fillOpacity={0.08}
                    stroke={color}
                    strokeOpacity={0.35}
                    strokeWidth={1}
                  />
                )}
                <RoleIcon
                  role={a.role}
                  cx={pos.x}
                  cy={pos.y}
                  size={size}
                  color={color}
                  strokeWidth={hover === a.id ? 1.7 : 1.4}
                />
                {/* Invisible hit area so small icons are still hoverable */}
                <circle
                  cx={pos.x}
                  cy={pos.y}
                  r={hitRadius}
                  fill="transparent"
                />
                {(derived.agents.length <= 24 || hover === a.id) && (
                  <text
                    x={pos.x}
                    y={pos.y + size * 0.65 + 11}
                    textAnchor="middle"
                    fontSize={9}
                    fontWeight={500}
                    fill="#353129"
                    style={{ pointerEvents: 'none' }}
                  >
                    {a.id}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {/* Sim time overlay */}
        <div className="absolute left-4 top-4 flex items-center gap-2 rounded-full border border-cream-400/70 bg-cream-50/90 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.22em] text-ink-500">
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              playing ? 'bg-rust animate-pulse' : 'bg-ink-300'
            }`}
          />
          <span>t = {fmt(simTime)}</span>
          <span className="text-ink-300">/ {fmt(derived.tMax)}</span>
        </div>

        {/* Live counters */}
        <div className="absolute right-4 top-4 flex gap-4 rounded-2xl border border-cream-400/70 bg-cream-50/90 px-4 py-2 font-mono text-[10px] uppercase tracking-[0.18em] text-ink-500">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-rust" />
            <span className="text-ink-300">sent</span>
            <span className="text-ink-900 tabular-nums">{counters.sent}</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-sage" />
            <span className="text-ink-300">recv</span>
            <span className="text-ink-900 tabular-nums">
              {counters.received}
            </span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber" />
            <span className="text-ink-300">flight</span>
            <span className="text-rust tabular-nums">{counters.inFlight}</span>
          </span>
          {derived.totalDropped > 0 && (
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-ink-300" />
              <span className="text-ink-300">drop</span>
              <span className="text-ink-900 tabular-nums">
                {counters.dropped}
              </span>
            </span>
          )}
        </div>
      </div>

      {/* Transport controls */}
      <div className="flex flex-col gap-3 rounded-2xl border border-cream-400/70 bg-cream-50 px-5 py-4 sm:flex-row sm:items-center">
        <button
          onClick={() => {
            if (simTime >= derived.tMax) setSimTime(derived.tMin);
            setPlaying((p) => !p);
          }}
          className="inline-flex h-9 w-20 items-center justify-center rounded-full bg-ink-900 text-cream-50 text-[0.85rem] font-medium hover:bg-ink-700 transition-colors"
        >
          {playing ? 'Pause' : simTime >= derived.tMax ? 'Replay' : 'Play'}
        </button>

        <input
          type="range"
          min={0}
          max={1000}
          value={pct * 10}
          onChange={(ev) => {
            const v = Number(ev.target.value) / 1000;
            setSimTime(derived.tMin + v * (derived.tMax - derived.tMin));
          }}
          className="flex-1 accent-rust"
        />

        <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.22em] text-ink-400">
          <span>speed</span>
          {[0.25, 0.5, 1, 2, 4].map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              className={`px-2 py-1 rounded ${
                speed === s
                  ? 'bg-ink-900 text-cream-50'
                  : 'text-ink-500 hover:bg-cream-200'
              }`}
            >
              {s}×
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Side panels (legend + agent table)                                */
/* ------------------------------------------------------------------ */

function Legend({ agents }: { agents: Agent[] }) {
  const roles = useMemo(() => {
    const m = new Map<string, number>();
    for (const a of agents) m.set(a.role, (m.get(a.role) ?? 0) + 1);
    return Array.from(m.entries());
  }, [agents]);

  return (
    <div className="rounded-2xl border border-cream-400/70 bg-cream-50 p-5">
      <h3 className="font-mono text-[10px] uppercase tracking-[0.22em] text-rust mb-4">
        Roles
      </h3>
      <ul className="space-y-2">
        {roles.map(([role, count]) => {
          const color = roleColor(role);
          return (
            <li
              key={role}
              className="flex items-center justify-between text-[0.88rem]"
            >
              <span className="flex items-center gap-2.5">
                <svg width={22} height={22} viewBox="0 0 22 22">
                  <RoleIcon
                    role={role}
                    cx={11}
                    cy={11}
                    size={20}
                    color={color}
                  />
                </svg>
                <span className="capitalize text-ink-700">{role}</span>
              </span>
              <span className="font-mono text-[11px] tabular-nums text-ink-400">
                {count}
              </span>
            </li>
          );
        })}
      </ul>
      <div className="mt-5 pt-4 border-t border-cream-400/60 space-y-2 text-[0.78rem] text-ink-500">
        <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-rust mb-2">
          Messages
        </p>
        <div className="flex items-center gap-2">
          <svg width={20} height={8} viewBox="0 0 20 8">
            <line
              x1="2"
              y1="4"
              x2="18"
              y2="4"
              stroke="#C45A3C"
              strokeWidth={2.2}
              strokeLinecap="round"
            />
            <circle cx="18" cy="4" r="1.6" fill="#C45A3C" />
          </svg>
          <span>send</span>
        </div>
        <div className="flex items-center gap-2">
          <svg width={20} height={8} viewBox="0 0 20 8">
            <line
              x1="2"
              y1="4"
              x2="18"
              y2="4"
              stroke="#B58432"
              strokeWidth={2.2}
              strokeLinecap="round"
            />
            <circle cx="18" cy="4" r="1.6" fill="#B58432" />
          </svg>
          <span>broadcast</span>
        </div>
        <div className="flex items-center gap-2">
          <svg width={20} height={8} viewBox="0 0 20 8">
            <line
              x1="2"
              y1="4"
              x2="18"
              y2="4"
              stroke="#8C8576"
              strokeWidth={2.2}
              strokeLinecap="round"
              strokeDasharray="2 2"
            />
          </svg>
          <span>dropped</span>
        </div>
      </div>
    </div>
  );
}

function MessageStream({
  derived,
  limit = 80,
}: {
  derived: Derived;
  limit?: number;
}) {
  const recent = useMemo(() => {
    const sorted = [...derived.flights].sort((a, b) => b.tStart - a.tStart);
    return sorted.slice(0, limit);
  }, [derived.flights, limit]);

  return (
    <div className="rounded-2xl border border-cream-400/70 bg-cream-50">
      <div className="border-b border-cream-400/70 px-5 py-3">
        <h3 className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-400">
          Latest messages
        </h3>
      </div>
      <ul className="max-h-[420px] overflow-y-auto divide-y divide-cream-400/40 text-[0.78rem]">
        {recent.map((f, i) => (
          <li
            key={i}
            className="flex items-center gap-2 px-4 py-2 hover:bg-cream-200/50 transition-colors"
          >
            <span className="font-mono text-[10px] text-ink-300 tabular-nums w-12 shrink-0 text-right">
              {f.tStart.toFixed(1)}
            </span>
            <span
              className="inline-block h-1.5 w-1.5 rounded-full shrink-0"
              style={{
                backgroundColor:
                  f.kind === 'dropped'
                    ? '#8C8576'
                    : f.kind === 'broadcast'
                    ? '#B58432'
                    : '#C45A3C',
              }}
            />
            <span className="font-mono text-[10px] text-ink-500 truncate">
              {f.source} → {f.target}
            </span>
            <span className="ml-auto truncate font-mono text-[10px] text-ink-400 max-w-[110px]">
              {f.msg}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function VisualizerPage() {
  const [scenarioId, setScenarioId] = useState<string>('auction');
  const [events, setEvents] = useState<TraceEvent[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [customName, setCustomName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load a bundled scenario
  const loadScenario = useCallback(async (id: string) => {
    const s = SCENARIOS.find((sc) => sc.id === id);
    if (!s) return;
    setLoading(true);
    setError(null);
    setCustomName(null);
    setScenarioId(id);
    try {
      const res = await fetch(s.file);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      const parsed = parseTrace(text);
      if (parsed.length === 0) throw new Error('Trace is empty');
      setEvents(parsed);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load trace');
      setEvents(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Defer to a microtask so the synchronous setState calls inside
    // loadScenario don't fire inside the effect body itself.
    void Promise.resolve().then(() => loadScenario('auction'));
  }, [loadScenario]);

  const handleFile = useCallback((file: File) => {
    setLoading(true);
    setError(null);
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const text = ev.target?.result as string;
        const parsed = parseTrace(text);
        if (parsed.length === 0) throw new Error('No valid events in file');
        setEvents(parsed);
        setCustomName(file.name);
        setScenarioId('custom');
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Bad file');
      } finally {
        setLoading(false);
      }
    };
    reader.readAsText(file);
  }, []);

  const derived = useMemo(
    () => (events ? derive(events) : null),
    [events],
  );

  return (
    <div className="bg-cream-100">
      {/* Header */}
      <section className="paper-texture border-b border-cream-400/70">
        <div className="mx-auto max-w-[1240px] px-6 sm:px-10 pt-20 pb-14">
          <div className="flex items-center gap-3 mb-10 animate-fade-in">
            <span className="inline-flex h-1.5 w-1.5 rounded-full bg-rust" />
            <span className="eyebrow">Visualizer · live playback</span>
          </div>

          <div className="grid gap-12 lg:grid-cols-[1.4fr_1fr] lg:items-end">
            <div className="animate-fade-in stagger-1 flex items-start gap-5">
              <svg
                width={64}
                height={64}
                viewBox="0 0 64 64"
                className="shrink-0 mt-3 hidden sm:block"
                aria-hidden
              >
                {/* nest mark: woven twigs forming an ellipse */}
                <ellipse
                  cx="32"
                  cy="38"
                  rx="26"
                  ry="14"
                  fill="none"
                  stroke="#C45A3C"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
                <ellipse
                  cx="32"
                  cy="36"
                  rx="20"
                  ry="9"
                  fill="none"
                  stroke="#B58432"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                />
                <path
                  d="M8 38 L56 36"
                  stroke="#221F1A"
                  strokeWidth="1.2"
                  strokeLinecap="round"
                  fill="none"
                />
                <path
                  d="M12 32 L52 44"
                  stroke="#C45A3C"
                  strokeWidth="1.2"
                  strokeLinecap="round"
                  fill="none"
                />
                <path
                  d="M12 44 L52 32"
                  stroke="#B58432"
                  strokeWidth="1.2"
                  strokeLinecap="round"
                  fill="none"
                />
                {/* egg */}
                <ellipse
                  cx="32"
                  cy="34"
                  rx="6"
                  ry="4.5"
                  fill="#F1DCD0"
                  stroke="#C45A3C"
                  strokeWidth="1"
                />
              </svg>
              <h1 className="font-display text-[clamp(2.6rem,6vw,5rem)] leading-[1.02] tracking-tight text-ink-900">
                Watch a<br />
                <span className="italic text-rust">simulation</span><br />
                actually move.
              </h1>
            </div>
            <p className="animate-fade-in stagger-2 text-[1.1rem] leading-[1.6] text-ink-500 max-w-md">
              Every twig is a real message from a real NEST trace. Pick a
              scenario, scrub the timeline, or drop in a{' '}
              <span className="font-mono text-rust">.jsonl</span> from your own{' '}
              <span className="font-mono text-rust">nest run</span>.
            </p>
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-[1240px] px-6 sm:px-10 py-10">
        {/* Scenario picker */}
        <div className="animate-fade-in stagger-1">
          <div className="flex items-center justify-between gap-4 mb-4">
            <h2 className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-400">
              Scenarios
            </h2>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-400 hover:text-rust transition-colors"
            >
              + load custom .jsonl
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".jsonl,.json,.ndjson"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFile(f);
              }}
            />
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {SCENARIOS.map((s) => {
              const active = scenarioId === s.id;
              return (
                <button
                  key={s.id}
                  onClick={() => loadScenario(s.id)}
                  className={`group relative overflow-hidden rounded-xl border px-4 py-3 text-left transition-all ${
                    active
                      ? 'border-rust bg-rust-bg/60'
                      : 'border-cream-400/70 bg-cream-50 hover:border-rust/40'
                  }`}
                >
                  {active && (
                    <span className="absolute left-0 top-0 h-full w-[3px] bg-rust" />
                  )}
                  <div
                    className={`text-[0.92rem] font-medium ${
                      active ? 'text-ink-900' : 'text-ink-900'
                    }`}
                  >
                    {s.name}
                  </div>
                  <div
                    className={`mt-1 text-[0.74rem] leading-snug ${
                      active ? 'text-ink-600' : 'text-ink-400'
                    }`}
                  >
                    {s.blurb}
                  </div>
                </button>
              );
            })}
            {customName && (
              <div className="rounded-xl border border-rust bg-rust-bg/40 px-4 py-3">
                <div className="text-[0.92rem] font-medium text-rust">
                  Custom
                </div>
                <div className="mt-1 text-[0.74rem] leading-snug text-ink-500 truncate">
                  {customName}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Status row */}
        {loading && (
          <p className="mt-8 font-mono text-[11px] uppercase tracking-[0.22em] text-ink-400">
            Loading trace…
          </p>
        )}
        {error && (
          <p className="mt-8 font-mono text-[11px] uppercase tracking-[0.22em] text-rust">
            {error}
          </p>
        )}

        {/* Summary + Player + side panels */}
        {derived && (
          <div className="mt-8 animate-fade-in stagger-2">
            {/* Summary */}
            <div className="mb-8 grid grid-cols-2 md:grid-cols-5 gap-6 border-t border-rust/40 pt-8">
              {[
                { label: 'Agents', value: derived.agents.length, accent: '#C45A3C' },
                { label: 'Messages', value: derived.flights.length, accent: '#B58432' },
                {
                  label: 'Sent',
                  value: derived.totalSent + derived.totalBroadcasts,
                  accent: '#5C6E5A',
                },
                { label: 'Dropped', value: derived.totalDropped, accent: '#8C8576' },
                {
                  label: 'Duration',
                  value: (derived.tMax - derived.tMin).toFixed(1),
                  suffix: 's',
                  accent: '#221F1A',
                },
              ].map((stat) => (
                <div key={stat.label}>
                  <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-ink-400 flex items-center gap-1.5">
                    <span
                      className="inline-block h-1 w-1 rounded-full"
                      style={{ backgroundColor: stat.accent }}
                    />
                    {stat.label}
                  </p>
                  <p className="mt-2 font-display text-[2rem] leading-none text-ink-900 tabular-nums">
                    {stat.value}
                    {'suffix' in stat && stat.suffix && (
                      <span className="ml-1 text-[1rem] text-rust">
                        {stat.suffix}
                      </span>
                    )}
                  </p>
                </div>
              ))}
            </div>

            {/* Player + sidebar */}
            <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
              <Player key={scenarioId} derived={derived} />
              <div className="space-y-6">
                <Legend agents={derived.agents} />
                <MessageStream derived={derived} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
