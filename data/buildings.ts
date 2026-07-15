export type Entrance = {
  id: string;
  coordinates: [number, number];
  approach: [number, number];
  heading: number;
  label: string;
  kind: "main" | "accessible" | "exit";
};

export type Building = {
  id: string;
  name: string;
  shortCode: string;
  category: string;
  subtitle: string;
  description: string;
  coordinates: [number, number];
  entrance: Entrance;
  entrances?: Entrance[];
  open: boolean;
  hours: string;
  imageClass: string;
  features: string[];
  gallery: string[];
  energy: {
    useType: string;
    system: string;
    demandKw: number;
    annualMwh: number;
    emissions: "Low" | "Medium" | "High";
    retrofit: string;
    score: number;
  };
  assetStatus: {
    modelStatus: "Queued" | "In progress" | "Ready" | "Needs review";
    meterStatus: "Missing" | "Estimated" | "Connected";
    dataQuality: "Draft" | "Field check" | "Verified";
    priority: "Low" | "Medium" | "High";
    lastInspection: string;
    nextStep: string;
  };
};

export const categories = ["All places", "Study", "Arts", "Dining", "Campus life", "History"];

export const buildings: Building[] = [
  {
    id: "baker-berry", name: "Baker-Berry Library", shortCode: "BB", category: "Study", subtitle: "The heart of scholarship on campus",
    description: "Dartmouth's iconic library brings historic architecture and bright, modern study spaces together under one clock tower.",
    coordinates: [-72.28913, 43.70535], entrance: { id: "main", coordinates: [-72.28912, 43.70491], approach: [-72.28912, 43.70434], heading: 0, label: "Green-facing main entrance", kind: "main" }, open: true, hours: "Open until 2:00 AM", imageClass: "baker", features: ["Accessible entrance", "Quiet floors", "Café", "Printers"], gallery: ["The Tower Room", "Berry Main Street", "Orozco Murals"],
    energy: { useType: "Library / academic", system: "District heat + electric", demandKw: 920, annualMwh: 4100, emissions: "Medium", retrofit: "Lighting controls and envelope audit", score: 72 },
    assetStatus: { modelStatus: "In progress", meterStatus: "Estimated", dataQuality: "Field check", priority: "High", lastInspection: "2026-07-14", nextStep: "Replace placeholder tower mass with optimized GLB" }
  },
  {
    id: "hopkins", name: "Hopkins Center for the Arts", shortCode: "HOP", category: "Arts", subtitle: "Performance, film, music, and making",
    description: "Known simply as the Hop, this is Dartmouth's creative crossroads—home to performances, studios, galleries, and spontaneous encounters.",
    coordinates: [-72.28858, 43.70187], entrance: { id: "main", coordinates: [-72.28855, 43.70212], approach: [-72.28854, 43.70258], heading: 180, label: "Hop plaza entrance", kind: "main" }, open: true, hours: "Open until 11:00 PM", imageClass: "hop", features: ["Wheelchair access", "Box office", "Gallery", "Restrooms"], gallery: ["Top of the Hop", "The Moore Theater", "Jewelry Studio"],
    energy: { useType: "Arts / performance", system: "District heat + high ventilation", demandKw: 760, annualMwh: 3600, emissions: "High", retrofit: "Demand-controlled ventilation study", score: 58 },
    assetStatus: { modelStatus: "Queued", meterStatus: "Estimated", dataQuality: "Draft", priority: "Medium", lastInspection: "Needs visit", nextStep: "Confirm roofline and theater volume before export" }
  },
  {
    id: "collis", name: "Collis Center", shortCode: "COL", category: "Campus life", subtitle: "Dartmouth's student living room",
    description: "A warm, lively center for food, student organizations, gatherings, and the everyday rhythm of campus life.",
    coordinates: [-72.2899353, 43.7027887],
    entrance: { id: "north-main", coordinates: [-72.28995, 43.70299], approach: [-72.28995, 43.70340], heading: 180, label: "North main entrance", kind: "main" },
    entrances: [
      { id: "north-main", coordinates: [-72.28995, 43.70299], approach: [-72.28995, 43.70340], heading: 180, label: "North main entrance", kind: "main" },
      { id: "east-accessible", coordinates: [-72.28969, 43.70279], approach: [-72.28930, 43.70279], heading: 270, label: "Main Street accessible entrance", kind: "accessible" },
      { id: "south-exit", coordinates: [-72.28995, 43.70258], approach: [-72.28995, 43.70225], heading: 0, label: "South exit", kind: "exit" },
      { id: "west-exit", coordinates: [-72.29023, 43.70276], approach: [-72.29058, 43.70276], heading: 90, label: "West exit", kind: "exit" }
    ],
    open: true, hours: "Open until 1:00 AM", imageClass: "collis", features: ["Elevator", "Dining", "Study space", "Gender-neutral restroom"], gallery: ["Common Ground", "Collis Café", "Student Involvement"],
    energy: { useType: "Student life / dining", system: "District heat + mixed air handling", demandKw: 680, annualMwh: 2950, emissions: "Medium", retrofit: "Kitchen exhaust and scheduling tune-up", score: 64 },
    assetStatus: { modelStatus: "Needs review", meterStatus: "Estimated", dataQuality: "Field check", priority: "Medium", lastInspection: "2026-07-13", nextStep: "Check entrances and service-side geometry" }
  },
  {
    id: "foco", name: "Class of 1953 Commons", shortCode: "53", category: "Dining", subtitle: "Campus dining with something for everyone",
    description: "Dartmouth's main dining hall offers a wide variety of stations and a sociable gathering space overlooking the heart of campus.",
    coordinates: [-72.29044, 43.70456], entrance: { id: "main", coordinates: [-72.29003, 43.70442], approach: [-72.28950, 43.70442], heading: 270, label: "Massachusetts Row entrance", kind: "main" }, open: true, hours: "Open until 8:30 PM", imageClass: "foco", features: ["Accessible entrance", "Vegan options", "Allergen station", "Seating"], gallery: ["The Hearth", "Main Dining Hall", "Courtyard"],
    energy: { useType: "Dining / assembly", system: "District heat + kitchen loads", demandKw: 980, annualMwh: 4300, emissions: "High", retrofit: "Heat recovery and kitchen equipment review", score: 55 },
    assetStatus: { modelStatus: "Queued", meterStatus: "Estimated", dataQuality: "Draft", priority: "High", lastInspection: "Needs visit", nextStep: "Capture dining/service massing for the first model pass" }
  },
  {
    id: "dartmouth-hall", name: "Dartmouth Hall", shortCode: "DH", category: "History", subtitle: "A campus landmark since 1784",
    description: "The beloved white-columned landmark anchors the east side of the Green and houses language and humanities classrooms.",
    coordinates: [-72.28658, 43.70371], entrance: { id: "main", coordinates: [-72.28687, 43.70371], approach: [-72.28743, 43.70370], heading: 90, label: "Front portico entrance", kind: "main" }, open: false, hours: "Opens tomorrow at 8:00 AM", imageClass: "dartmouth", features: ["Historic building", "Classrooms", "Accessible entrance", "Restrooms"], gallery: ["Front Portico", "Language Commons", "The Green View"],
    energy: { useType: "Academic / historic", system: "District heat", demandKw: 410, annualMwh: 1500, emissions: "Medium", retrofit: "Historic envelope preservation strategy", score: 67 },
    assetStatus: { modelStatus: "In progress", meterStatus: "Estimated", dataQuality: "Field check", priority: "High", lastInspection: "2026-07-14", nextStep: "Preserve front facade proportions in GLB export" }
  },
  {
    id: "life-sciences", name: "Class of 1978 Life Sciences", shortCode: "LSC", category: "Study", subtitle: "Research inspired by the natural world",
    description: "A modern, high-performance research building with expansive lab spaces and a greenhouse overlooking the north campus.",
    coordinates: [-72.28578, 43.70887], entrance: { id: "main", coordinates: [-72.28605, 43.70854], approach: [-72.28632, 43.70814], heading: 34, label: "South atrium entrance", kind: "main" }, open: true, hours: "Open until 10:00 PM", imageClass: "lsc", features: ["LEED Platinum", "Accessible entrance", "Greenhouse", "Study nooks"], gallery: ["Atrium", "Greenhouse", "Teaching Lab"],
    energy: { useType: "Laboratory / research", system: "High-performance lab systems", demandKw: 1220, annualMwh: 5400, emissions: "Medium", retrofit: "Lab airflow optimization", score: 79 },
    assetStatus: { modelStatus: "Queued", meterStatus: "Estimated", dataQuality: "Draft", priority: "High", lastInspection: "Needs visit", nextStep: "Include north-campus lab massing and greenhouse zone" }
  }
];
