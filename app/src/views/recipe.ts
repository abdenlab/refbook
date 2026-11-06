// An edition's recipe, as editions.parquet stores it (the recipe JSON), and the
// words the app uses for its parts.

export interface Recipe {
  select: ({ assembly: string; roles: string[]; accessions?: string[]; placed_on?: string[] }
    | { roots: string[] } | { collection: string; groups: string[] })[];
  mask?: { layer: string; with: string }[];
  alphabet?: { iupac?: string };
  rename: { namespace: string; by_role?: Record<string, string>; map?: Record<string, string>; template?: Record<string, string> };
}

const ROLE_LABELS: Record<string, string> = {
  "assembled-molecule": "chromosomes", "unlocalized-scaffold": "unlocalized scaffolds",
  "unplaced-scaffold": "unplaced scaffolds", "alt-scaffold": "alt scaffolds",
  "fix-patch": "fix patches", "novel-patch": "novel patches",
};

export const role = (r: string) => ROLE_LABELS[r] ?? r;
