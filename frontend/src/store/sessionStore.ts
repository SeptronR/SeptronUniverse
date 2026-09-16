import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { queryClient } from '@/lib/queryClient';

export interface AcademicYearOption {
  id: string;
  name: string;
  is_current?: boolean;
}
export interface TermOption {
  id: string;
  name: string;
  academic_year_id: string;
  is_current?: boolean;
}

interface SessionState {
  institutionId: string | null;
  institutionName: string | null;
  collegeId: string | null;
  collegeName: string | null;
  academicYearId: string | null;
  termId: string | null;
  years: AcademicYearOption[];
  terms: TermOption[];
  readOnly: boolean;
  setInstitution: (id: string | null, name?: string | null) => void;
  setCollege: (id: string | null, name?: string | null) => void;
  setYear: (id: string | null) => void;
  setTerm: (id: string | null) => void;
  setYears: (years: AcademicYearOption[], terms: TermOption[]) => void;
  setReadOnly: (v: boolean) => void;
  reset: () => void;
}

const initial = {
  institutionId: null,
  institutionName: null,
  collegeId: null,
  collegeName: null,
  academicYearId: null,
  termId: null,
  years: [],
  terms: [],
  readOnly: false,
};

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      ...initial,
      // switching institution/college invalidates every cached list (tenant/college scoped data)
      setInstitution: (id, name = null) => {
        queryClient.clear();
        set({ institutionId: id, institutionName: name, collegeId: null, collegeName: null });
      },
      setCollege: (id, name = null) => {
        queryClient.clear();
        set({ collegeId: id, collegeName: name });
      },
      setYear: (id) => set({ academicYearId: id, termId: null }),
      setTerm: (id) => set({ termId: id }),
      setYears: (years, terms) => set({ years, terms }),
      setReadOnly: (v) => set({ readOnly: v }),
      reset: () => set({ ...initial }),
    }),
    { name: 'universe-session', partialize: (s) => ({ ...s, readOnly: false }) },
  ),
);
