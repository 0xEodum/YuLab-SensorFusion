// Source scene overlays and helper lines are presentation only. The imported
// static geometry comes from the model components themselves.
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
export const Html = () => null;
export const Line = () => null;
export const Edges = () => null;
export const RoundedBox = ({ args, radius, smoothness, children, ...props }) => ({
  type: "mesh",
  props: {
    ...props,
    geometry: new RoundedBoxGeometry(args[0], args[1], args[2], smoothness ?? 2, radius ?? 0.05),
    children,
  },
});
