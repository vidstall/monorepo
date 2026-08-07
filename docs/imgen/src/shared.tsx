import React from "react";

export const theme = {
  bg: "#ffffff",
  panel: "#f8fafc",
  text: "#0f172a",
  subtext: "#475569",
  line: "#94a3b8",
};

export type Point = { x: number; y: number };

export function Box(props: {
  title: string;
  subtitle?: string;
  accent: string;
  center: Point;
  width: number;
  height: number;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        position: "absolute",
        left: props.center.x - props.width / 2,
        top: props.center.y - props.height / 2,
        width: props.width,
        height: props.height,
        padding: "18px 16px",
        borderRadius: 14,
        background: theme.panel,
        border: `2px solid ${props.accent}`,
        color: theme.text,
        textAlign: "center",
      }}
    >
      <div style={{ display: "flex", fontSize: 22, fontWeight: 700 }}>{props.title}</div>
      {props.subtitle && (
        <div style={{ display: "flex", fontSize: 14, color: theme.subtext, marginTop: 6 }}>
          {props.subtitle}
        </div>
      )}
    </div>
  );
}

// Straight connecting line drawn as a rotated rectangle between two points --
// satori has no <line>/<svg> primitive, so this is a div sized to the
// distance between the points and rotated to the angle between them.
export function Line(props: { a: Point; b: Point; color?: string; thickness?: number }) {
  const thickness = props.thickness ?? 3;
  const dx = props.b.x - props.a.x;
  const dy = props.b.y - props.a.y;
  const length = Math.sqrt(dx * dx + dy * dy);
  const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
  // satori rotates around the element's own center regardless of
  // transform-origin, so size/position the div centered on the midpoint of
  // a/b (its default center pivot) rather than anchoring at point a.
  const midX = (props.a.x + props.b.x) / 2;
  const midY = (props.a.y + props.b.y) / 2;
  return (
    <div
      style={{
        display: "flex",
        position: "absolute",
        left: midX - length / 2,
        top: midY - thickness / 2,
        width: length,
        height: thickness,
        background: props.color ?? theme.line,
        transform: `rotate(${angle}deg)`,
      }}
    />
  );
}

export function Label(props: { at: Point; label: string; width?: number }) {
  return (
    <div
      style={{
        display: "flex",
        position: "absolute",
        left: props.at.x - (props.width ?? 240) / 2,
        top: props.at.y - 20,
        width: props.width ?? 240,
        justifyContent: "center",
        textAlign: "center",
        fontSize: 14,
        color: theme.subtext,
        background: theme.bg,
        padding: "4px 8px",
        borderRadius: 6,
      }}
    >
      {props.label}
    </div>
  );
}

// ── Sequence diagram helper ──────────────────────────────────────────
// A small reusable layout for "who sends what, in what order" protocol
// diagrams: actors become vertical lifelines across the top, and each
// message becomes one horizontal row with an arrow pointing from sender to
// receiver. Built entirely from Box/Line/Label so it stays inside satori's
// flexbox-only constraints (see docs/imgen/README.md).

export type SeqMessage = {
  /** Actor name sending the message (must match an entry in `actors`). */
  from: string;
  /** Actor name receiving the message (must match an entry in `actors`); same as `from` for a self/internal step. */
  to: string;
  /** Short message name/type shown on the arrow, e.g. "join" or "routerRtpCapabilities". */
  label: string;
  /** Optional second line of detail shown under the message label. */
  detail?: string;
};

const SEQ_COL_WIDTH = 340;
const SEQ_MARGIN_X = 170;
// Title + optional subtitle band above the first actor row.
const SEQ_TITLE_BAND = 90;
const SEQ_ACTOR_TOP = SEQ_TITLE_BAND;
const SEQ_ACTOR_HEIGHT = 84;
const SEQ_ROW_HEIGHT = 92;
const SEQ_BOTTOM_MARGIN = 50;

export function sequenceDiagramSize(actors: string[], messages: SeqMessage[]) {
  const width = SEQ_MARGIN_X * 2 + SEQ_COL_WIDTH * Math.max(1, actors.length - 1);
  const height =
    SEQ_ACTOR_TOP + SEQ_ACTOR_HEIGHT + messages.length * SEQ_ROW_HEIGHT + SEQ_BOTTOM_MARGIN;
  return { width, height };
}

export function SequenceDiagram(props: {
  title: string;
  subtitle?: string;
  actors: string[];
  /** Accent color per actor name; falls back to theme.line for unlisted actors. */
  accent?: Record<string, string>;
  messages: SeqMessage[];
}) {
  const { actors, messages, accent = {} } = props;
  const { width, height } = sequenceDiagramSize(actors, messages);
  const actorCenterY = SEQ_ACTOR_TOP + SEQ_ACTOR_HEIGHT / 2;
  const lifelineBottom = SEQ_ACTOR_TOP + SEQ_ACTOR_HEIGHT + messages.length * SEQ_ROW_HEIGHT;
  const actorX = (i: number) => SEQ_MARGIN_X + i * SEQ_COL_WIDTH;
  const colorOf = (name: string) => accent[name] ?? theme.line;

  return (
    <div
      style={{
        display: "flex",
        width,
        height,
        padding: 0,
        background: theme.bg,
        fontFamily: "Inter",
        position: "relative",
      }}
    >
      <div
        style={{
          display: "flex",
          position: "absolute",
          left: 0,
          top: 12,
          width,
          justifyContent: "center",
          fontSize: 26,
          fontWeight: 700,
          color: theme.text,
        }}
      >
        {props.title}
      </div>
      {props.subtitle && (
        <div
          style={{
            display: "flex",
            position: "absolute",
            left: 0,
            top: 44,
            width,
            justifyContent: "center",
            fontSize: 15,
            color: theme.subtext,
          }}
        >
          {props.subtitle}
        </div>
      )}

      {/* Lifelines -- drawn first so actor boxes and arrows sit on top */}
      {actors.map((a, i) => (
        <Line
          key={`life-${a}`}
          a={{ x: actorX(i), y: SEQ_ACTOR_TOP + SEQ_ACTOR_HEIGHT }}
          b={{ x: actorX(i), y: lifelineBottom }}
          color={theme.line}
          thickness={2}
        />
      ))}

      {/* Message arrows */}
      {messages.map((m, i) => {
        const fromI = actors.indexOf(m.from);
        const toI = actors.indexOf(m.to);
        const y = SEQ_ACTOR_TOP + SEQ_ACTOR_HEIGHT + (i + 1) * SEQ_ROW_HEIGHT - SEQ_ROW_HEIGHT / 2;
        const color = colorOf(m.from);
        if (fromI === toI) {
          // Self/internal step: a short stub off the lifeline, not a cross-actor arrow.
          // Stubs point toward whichever side has room -- left for the last actor
          // (a right-pointing stub there would run off the canvas), right otherwise.
          const x = actorX(fromI);
          const pointLeft = fromI === actors.length - 1 && fromI !== 0;
          const stubEnd = pointLeft ? x - 90 : x + 90;
          const labelX = pointLeft ? stubEnd - 130 : stubEnd + 130;
          return (
            <div key={`msg-${i}`} style={{ display: "flex" }}>
              <Line a={{ x, y }} b={{ x: stubEnd, y }} color={color} thickness={2} />
              <Label
                at={{ x: labelX, y }}
                width={260}
                label={m.detail ? `${m.label} — ${m.detail}` : m.label}
              />
            </div>
          );
        }
        const dir = toI > fromI ? ">>" : "<<";
        const midX = (actorX(fromI) + actorX(toI)) / 2;
        return (
          <div key={`msg-${i}`} style={{ display: "flex" }}>
            <Line a={{ x: actorX(fromI), y }} b={{ x: actorX(toI), y }} color={color} thickness={2} />
            <div
              style={{
                display: "flex",
                position: "absolute",
                left: (toI > fromI ? actorX(toI) - 22 : actorX(toI) + 6),
                top: y - 9,
                fontSize: 16,
                color,
                fontWeight: 700,
              }}
            >
              {dir}
            </div>
            <Label
              at={{ x: midX, y: y - 22 }}
              width={Math.min(SEQ_COL_WIDTH - 20, 300)}
              label={m.detail ? `${m.label} — ${m.detail}` : m.label}
            />
          </div>
        );
      })}

      {/* Actor boxes, drawn last so they sit above their own lifeline's top end */}
      {actors.map((a, i) => (
        <Box
          key={`actor-${a}`}
          title={a}
          accent={colorOf(a)}
          center={{ x: actorX(i), y: actorCenterY }}
          width={SEQ_COL_WIDTH - 60}
          height={SEQ_ACTOR_HEIGHT}
        />
      ))}
    </div>
  );
}
