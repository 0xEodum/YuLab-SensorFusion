// The supplied RQ-4 source is external to this repository. Keep local geometry
// corrections here so a catalog reimport reproduces the reviewed parked pose.
export function correctRq4Source(source) {
  const replaceOnce = (before, after) => {
    const first = source.indexOf(before);
    if (first < 0 || source.indexOf(before, first + before.length) >= 0)
      throw new Error(`RQ-4 source correction anchor missing or ambiguous: ${before.slice(0, 48)}`);
    source = source.replace(before, after);
  };

  // A Three.js torus starts in the XY plane, perpendicular to the nacelle's Z axis.
  replaceOnce(
    '<mesh position={[0, 1.22, -1.72]} rotation={[Math.PI / 2, 0, 0]}>',
    '<mesh position={[0, 1.22, -1.72]}>',
  );
  // The nose leg now enters the lower fuselage rather than ending at its skin.
  replaceOnce(
    '<cylinderGeometry args={[0.06, 0.07, 1.1, 6]} />',
    '<cylinderGeometry args={[0.06, 0.07, 1.3, 6]} />',
  );
  // The main legs reach the wing belly; diagonal trunnions visibly meet the fuselage.
  replaceOnce(
    '<cylinderGeometry args={[0.08, 0.09, 1.3, 6]} />',
    '<cylinderGeometry args={[0.08, 0.09, 1.5, 6]} />',
  );
  replaceOnce(
    '          {/* axle */}',
    `          <mesh position={[side * 1.05, -0.36, 0]} rotation={[0, 0, side * -1.79]} castShadow>
            <cylinderGeometry args={[0.06, 0.07, 1.15, 6]} />
            <meshStandardMaterial {...strut} />
          </mesh>
          {/* axle */}`,
  );
  return source;
}
