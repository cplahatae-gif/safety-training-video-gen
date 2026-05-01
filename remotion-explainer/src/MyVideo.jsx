import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate } from "remotion";

export const MyVideo = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const opacity = interpolate(frame, [0, 30], [0, 1], { extrapolateRight: "clamp" });
  const translateY = interpolate(frame, [0, 30], [20, 0], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: "#1a1a2e", justifyContent: "center", alignItems: "center" }}>
      <div style={{ opacity, transform: `translateY(${translateY}px)`, textAlign: "center", color: "white" }}>
        <h1 style={{ fontSize: 64, fontWeight: "bold", margin: 0 }}>안전 교육</h1>
        <p style={{ fontSize: 32, marginTop: 16, color: "#aaa" }}>설명 영상 예시</p>
      </div>
    </AbsoluteFill>
  );
};
