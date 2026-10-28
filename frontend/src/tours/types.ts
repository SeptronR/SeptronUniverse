/** Guided-tour definition (Prompts/39 §39.6 ``tour_service``): ``target`` is a CSS selector, usually ``[data-tour="…"]``. */
export interface TourStepDef {
  target: string;
  title: string;
  body: string;
  placement?: 'top' | 'bottom' | 'left' | 'right';
}
export interface TourDefinition {
  key: string;
  route: string;
  roles: string[];
  version: number;
  title: string;
  steps: TourStepDef[];
}
