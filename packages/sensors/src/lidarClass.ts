/** Stable simulator-truth IDs. These labels are not measured by the LiDAR receiver. */
export const LIDAR_CLASS = {
  unclassified: 0,
  terrain: 1,
  pavement: 2,
  marking: 3,
  building: 4,
  vegetation: 5,
  rock: 6,
  fence: 7,
  aircraft: 8,
  ground_vehicle: 9,
  ship: 10,
  water: 11,
} as const;

export type LidarClassName = keyof typeof LIDAR_CLASS;

export const LIDAR_CLASS_TABLE: readonly { id: number; name: LidarClassName; color: string }[] = [
  { id: 0, name: "unclassified", color: "#b9c2cc" },
  { id: 1, name: "terrain", color: "#bf9460" },
  { id: 2, name: "pavement", color: "#7eb3c5" },
  { id: 3, name: "marking", color: "#f4df76" },
  { id: 4, name: "building", color: "#cc83cc" },
  { id: 5, name: "vegetation", color: "#69be77" },
  { id: 6, name: "rock", color: "#a7a3a0" },
  { id: 7, name: "fence", color: "#de9b87" },
  { id: 8, name: "aircraft", color: "#f47863" },
  { id: 9, name: "ground_vehicle", color: "#e9af63" },
  { id: 10, name: "ship", color: "#6e91ee" },
  { id: 11, name: "water", color: "#5d8bd4" },
];

export function lidarClassId(value: unknown): number {
  if (value === undefined || value === null) return LIDAR_CLASS.unclassified;
  if (value === "background") return LIDAR_CLASS.unclassified;
  if (typeof value !== "string" || !Object.hasOwn(LIDAR_CLASS, value))
    throw new Error(`Unknown LiDAR reference class: ${String(value)}`);
  return LIDAR_CLASS[value as LidarClassName];
}
