import { facultyTours } from './faculty';
import { otherTours } from './others';
import { parentTours } from './parent';
import { studentTours } from './student';
import type { TourDefinition } from './types';

/** Tour registry — the source of truth; `npm run tours:export` writes backend/app/core/tours_snapshot.json. */
export const TOURS: TourDefinition[] = [...studentTours, ...parentTours, ...facultyTours, ...otherTours];
export type { TourDefinition, TourStepDef } from './types';
