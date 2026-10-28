import {
  Activity, AlertCircle, Award, BadgeCheck, BarChart3, Bed, Bell, Book, BookOpen, Briefcase, Bus, Calendar, CalendarCheck,
  CheckCircle, CheckSquare, ClipboardList, Database, Edit, FileQuestion, FilePlus, FilePen, FileText, FlaskConical,
  Folder, GraduationCap, Grid3x3, Heart, History, Home, Contact, IndianRupee, Inbox, Library, List, ListChecks, ListOrdered,
  LogOut, Map, Megaphone, MessageSquare, Package, Repeat, RotateCcw, Scan, Scroll, Settings, Shield, Star, TrendingUp,
  User, UserCheck, Users, Utensils, Wallet, Wrench, type LucideIcon,
} from 'lucide-react';

const ICONS: Record<string, LucideIcon> = {
  activity: Activity, 'alert-circle': AlertCircle, award: Award, 'badge-check': BadgeCheck, 'bar-chart': BarChart3, bed: Bed,
  bell: Bell, book: Book, 'book-open': BookOpen, briefcase: Briefcase, bus: Bus, calendar: Calendar, 'calendar-check': CalendarCheck,
  'check-circle': CheckCircle, 'check-square': CheckSquare, 'clipboard-list': ClipboardList, database: Database, edit: Edit,
  'file-question': FileQuestion, 'file-plus': FilePlus, 'file-signature': FilePen, 'file-text': FileText, flask: FlaskConical,
  folder: Folder, 'graduation-cap': GraduationCap, grid: Grid3x3, heart: Heart, history: History, home: Home, 'id-card': Contact,
  'indian-rupee': IndianRupee, inbox: Inbox, library: Library, list: List, 'list-checks': ListChecks, 'list-ordered': ListOrdered,
  'log-out': LogOut, map: Map, megaphone: Megaphone, 'message-square': MessageSquare, package: Package, repeat: Repeat,
  'rotate-ccw': RotateCcw, scan: Scan, scroll: Scroll, settings: Settings, shield: Shield, star: Star, 'trending-up': TrendingUp,
  user: User, 'user-check': UserCheck, users: Users, utensils: Utensils, wallet: Wallet, wrench: Wrench,
};

export function NavIcon({ name, className = 'h-5 w-5' }: { name: string; className?: string }) {
  const I = ICONS[name] ?? Grid3x3;
  return <I className={className} aria-hidden="true" />;
}
