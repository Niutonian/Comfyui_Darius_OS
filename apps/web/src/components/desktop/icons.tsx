import type { ReactNode, SVGProps } from "react";
import type { AppId } from "@/lib/desktop-apps";

/**
 * Darius desktop icon set: 24px grid, 1.6 stroke, rounded joins. Drawn to sit with
 * lucide's weight but read as one family on the rail, windows and launcher.
 */
type IconProps = SVGProps<SVGSVGElement> & { size?: number };
function Icon({ size = 20, children, ...props }: IconProps & { children: ReactNode }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...props}>{children}</svg>;
}

export const CanvasIcon = (p: IconProps) => <Icon {...p}><rect x="3" y="3.5" width="8.5" height="7" rx="2" /><rect x="12.5" y="13.5" width="8.5" height="7" rx="2" /><path d="M11.5 7h2.8a2.2 2.2 0 0 1 2.2 2.2v4.3" strokeDasharray="1.6 2.2" /><circle cx="16.5" cy="13.5" r=".6" fill="currentColor" /></Icon>;
export const ChatIcon = (p: IconProps) => <Icon {...p}><path d="M6 4.5h12A2.5 2.5 0 0 1 20.5 7v8a2.5 2.5 0 0 1-2.5 2.5h-6.2L7.5 20.5v-3H6A2.5 2.5 0 0 1 3.5 15V7A2.5 2.5 0 0 1 6 4.5Z" /><path d="M8 11h.01M12 11h.01M16 11h.01" strokeWidth={2.4} /></Icon>;
export const LibraryIcon = (p: IconProps) => <Icon {...p}><rect x="7" y="3.5" width="13.5" height="12.5" rx="2.5" /><path d="M3.5 8v9.5a3 3 0 0 0 3 3H16" /><path d="m7 13.5 3.6-3.4 2.8 2.6 2.1-1.8 5 4.2" /><circle cx="16.2" cy="7.6" r="1.2" /></Icon>;
export const IdeasIcon = (p: IconProps) => <Icon {...p}><path d="M6 3.5h12A2.5 2.5 0 0 1 20.5 6v8.3l-6.2 6.2H6A2.5 2.5 0 0 1 3.5 18V6A2.5 2.5 0 0 1 6 3.5Z" /><path d="M14.3 20.5v-3.7a2.5 2.5 0 0 1 2.5-2.5h3.7" /><path d="M8 8.5h8M8 12h5" /></Icon>;
export const CharactersIcon = (p: IconProps) => <Icon {...p}><circle cx="12" cy="8.5" r="3.8" /><path d="M4.5 20.5c1.3-3.8 4.1-6 7.5-6s6.2 2.2 7.5 6" /></Icon>;
export const ScenesIcon = (p: IconProps) => <Icon {...p}><rect x="3" y="4.5" width="18" height="15" rx="2.5" /><path d="m3 16 5.2-5.2 4.3 4.3 3-3L21 17.5" /><circle cx="16" cy="8.8" r="1.4" /></Icon>;
export const ShotsIcon = (p: IconProps) => <Icon {...p}><rect x="3" y="9" width="18" height="11.5" rx="2.2" /><path d="M3.4 9 5.6 4.2a1.2 1.2 0 0 1 1.1-.7H20l-2 5.5" /><path d="m9.5 3.6-2.4 5.3M15 3.6l-2.4 5.3" /></Icon>;
export const MapIcon = (p: IconProps) => <Icon {...p}><circle cx="6" cy="7" r="2.6" /><circle cx="18" cy="6" r="2.6" /><circle cx="12.5" cy="18" r="2.6" /><path d="M8.6 7.2 15.4 6.3M7.3 9.3l4 6.4M17 8.5l-3.4 7.1" /></Icon>;
export const EditIcon = (p: IconProps) => <Icon {...p}><rect x="3" y="3.5" width="18" height="10.5" rx="2.2" /><path d="m10.5 6.8 4 2-4 2z" /><rect x="3" y="16.5" width="7" height="4" rx="1.2" /><rect x="12" y="16.5" width="9" height="4" rx="1.2" /></Icon>;
export const CloudIcon = (p: IconProps) => <Icon {...p}><path d="M7.2 18.5a4.2 4.2 0 0 1-.6-8.4 5.8 5.8 0 0 1 11.1-1.2 4.8 4.8 0 0 1-.2 9.6Z" /><path d="M12 10.5v5M9.5 13h5" /></Icon>;
export const WorkflowsIcon = (p: IconProps) => <Icon {...p}><path d="M12 3 5 6v5.2c0 4.4 2.9 7.9 7 9.8 4.1-1.9 7-5.4 7-9.8V6Z" /><path d="m9 12 2.2 2.2L15.5 10" /></Icon>;
export const SettingsIcon = (p: IconProps) => <Icon {...p}><path d="M4 7h9.5M18.5 7H20M4 17h2.5M11.5 17H20" /><circle cx="16" cy="7" r="2.5" /><circle cx="9" cy="17" r="2.5" /></Icon>;
export const QueueIcon = (p: IconProps) => <Icon {...p}><path d="M4 6h16M4 12h9M4 18h6" /><circle cx="17.5" cy="16.5" r="3.5" /><path d="M17.5 15v1.6l1 .9" /></Icon>;
export const LauncherIcon = (p: IconProps) => <Icon {...p}><rect x="3.5" y="3.5" width="7" height="7" rx="2" /><rect x="13.5" y="3.5" width="7" height="7" rx="2" /><rect x="3.5" y="13.5" width="7" height="7" rx="2" /><rect x="13.5" y="13.5" width="7" height="7" rx="2" /></Icon>;
export const MinimizeIcon = (p: IconProps) => <Icon {...p}><path d="M6 12h12" /></Icon>;
export const MaximizeIcon = (p: IconProps) => <Icon {...p}><rect x="5" y="5" width="14" height="14" rx="3" /></Icon>;
export const RestoreIcon = (p: IconProps) => <Icon {...p}><rect x="4.5" y="8" width="11.5" height="11.5" rx="2.5" /><path d="M8 4.5h8.5A3 3 0 0 1 19.5 7.5V16" /></Icon>;
export const CloseIcon = (p: IconProps) => <Icon {...p}><path d="m6.5 6.5 11 11M17.5 6.5l-11 11" /></Icon>;

export const appIcons: Record<AppId, (props: IconProps) => ReactNode> = {
  chat: ChatIcon, library: LibraryIcon, ideas: IdeasIcon, characters: CharactersIcon, scenes: ScenesIcon, shots: ShotsIcon,
  cloud: CloudIcon, workflows: WorkflowsIcon, map: MapIcon, edit: EditIcon, settings: SettingsIcon,
};
