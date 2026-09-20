import React, { useEffect, useState } from "react";
import { Text } from "ink";

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
export function WorkingIndicator({
  label,
  animate,
}: {
  label: string;
  animate: boolean;
}): React.JSX.Element {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    if (!animate) return;
    const timer = setInterval(
      () => setFrame((value) => (value + 1) % FRAMES.length),
      100,
    );
    return () => clearInterval(timer);
  }, [animate]);
  return (
    <Text>
      {animate ? FRAMES[frame] : "·"} {label}
    </Text>
  );
}
