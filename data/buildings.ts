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
};

export const categories = ["All places", "Study", "Arts", "Dining", "Campus life", "History"];

export const buildings: Building[] = [
  {
    id: "baker-berry", name: "Baker-Berry Library", shortCode: "BB", category: "Study", subtitle: "The heart of scholarship on campus",
    description: "Dartmouth's iconic library brings historic architecture and bright, modern study spaces together under one clock tower.",
    coordinates: [-72.28913, 43.70535], entrance: { id: "main", coordinates: [-72.28912, 43.70491], approach: [-72.28912, 43.70434], heading: 0, label: "Green-facing main entrance", kind: "main" }, open: true, hours: "Open until 2:00 AM", imageClass: "baker", features: ["Accessible entrance", "Quiet floors", "Café", "Printers"], gallery: ["The Tower Room", "Berry Main Street", "Orozco Murals"]
  },
  {
    id: "hopkins", name: "Hopkins Center for the Arts", shortCode: "HOP", category: "Arts", subtitle: "Performance, film, music, and making",
    description: "Known simply as the Hop, this is Dartmouth's creative crossroads—home to performances, studios, galleries, and spontaneous encounters.",
    coordinates: [-72.28858, 43.70187], entrance: { id: "main", coordinates: [-72.28855, 43.70212], approach: [-72.28854, 43.70258], heading: 180, label: "Hop plaza entrance", kind: "main" }, open: true, hours: "Open until 11:00 PM", imageClass: "hop", features: ["Wheelchair access", "Box office", "Gallery", "Restrooms"], gallery: ["Top of the Hop", "The Moore Theater", "Jewelry Studio"]
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
    open: true, hours: "Open until 1:00 AM", imageClass: "collis", features: ["Elevator", "Dining", "Study space", "Gender-neutral restroom"], gallery: ["Common Ground", "Collis Café", "Student Involvement"]
  },
  {
    id: "foco", name: "Class of 1953 Commons", shortCode: "53", category: "Dining", subtitle: "Campus dining with something for everyone",
    description: "Dartmouth's main dining hall offers a wide variety of stations and a sociable gathering space overlooking the heart of campus.",
    coordinates: [-72.29044, 43.70456], entrance: { id: "main", coordinates: [-72.29003, 43.70442], approach: [-72.28950, 43.70442], heading: 270, label: "Massachusetts Row entrance", kind: "main" }, open: true, hours: "Open until 8:30 PM", imageClass: "foco", features: ["Accessible entrance", "Vegan options", "Allergen station", "Seating"], gallery: ["The Hearth", "Main Dining Hall", "Courtyard"]
  },
  {
    id: "dartmouth-hall", name: "Dartmouth Hall", shortCode: "DH", category: "History", subtitle: "A campus landmark since 1784",
    description: "The beloved white-columned landmark anchors the east side of the Green and houses language and humanities classrooms.",
    coordinates: [-72.28658, 43.70371], entrance: { id: "main", coordinates: [-72.28687, 43.70371], approach: [-72.28743, 43.70370], heading: 90, label: "Front portico entrance", kind: "main" }, open: false, hours: "Opens tomorrow at 8:00 AM", imageClass: "dartmouth", features: ["Historic building", "Classrooms", "Accessible entrance", "Restrooms"], gallery: ["Front Portico", "Language Commons", "The Green View"]
  },
  {
    id: "life-sciences", name: "Class of 1978 Life Sciences", shortCode: "LSC", category: "Study", subtitle: "Research inspired by the natural world",
    description: "A modern, high-performance research building with expansive lab spaces and a greenhouse overlooking the north campus.",
    coordinates: [-72.28578, 43.70887], entrance: { id: "main", coordinates: [-72.28605, 43.70854], approach: [-72.28632, 43.70814], heading: 34, label: "South atrium entrance", kind: "main" }, open: true, hours: "Open until 10:00 PM", imageClass: "lsc", features: ["LEED Platinum", "Accessible entrance", "Greenhouse", "Study nooks"], gallery: ["Atrium", "Greenhouse", "Teaching Lab"]
  }
];
