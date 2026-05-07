import type { ReactNode, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function base(props: IconProps): IconProps {
  return {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
    ...props,
  };
}

export function GearIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
    </svg>
  );
}

export function BellIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}

export function HomeIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <path d="M3 11l9-8 9 8" />
      <path d="M5 10v10h14V10" />
    </svg>
  );
}

// Tenant: building / org icon
export function TenantIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <path d="M3 21V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v16" />
      <path d="M16 9h3a2 2 0 0 1 2 2v10" />
      <path d="M7 7h2M7 11h2M7 15h2M11 7h2M11 11h2M11 15h2" />
    </svg>
  );
}

// Farm: barn-ish silhouette
export function FarmIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <path d="M3 11 12 4l9 7" />
      <path d="M5 10v10h14V10" />
      <path d="M9 20v-5h6v5" />
    </svg>
  );
}

// Block: grid cell
export function BlockIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}

export function InsightsIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <path d="M3 3v18h18" />
      <path d="M7 14l4-4 3 3 5-7" />
    </svg>
  );
}

export function PlanIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9h18" />
      <path d="M8 13h6M8 17h4" />
    </svg>
  );
}

export function AlertsIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
      <path d="M10.3 3.7 1.8 18.4a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.7a2 2 0 0 0-3.4 0Z" />
    </svg>
  );
}

export function ReportsIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
      <path d="M9 13h6M9 17h6" />
    </svg>
  );
}

export function LandUnitsIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <path d="M3 6l9-3 9 3" />
      <path d="M3 18l9 3 9-3" />
      <path d="M3 6v12M21 6v12M12 3v18" />
    </svg>
  );
}

export function RulesIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <path d="M3 6h18M3 12h18M3 18h12" />
    </svg>
  );
}

export function ImageryIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="M21 15l-5-5-7 7" />
    </svg>
  );
}

export function UsersIcon(props: IconProps): ReactNode {
  return (
    <svg {...base(props)}>
      <circle cx="9" cy="8" r="3" />
      <path d="M3 21c0-3 3-5 6-5s6 2 6 5" />
      <circle cx="17" cy="9" r="2" />
      <path d="M15 21c0-2 2-3.5 4-3.5" />
    </svg>
  );
}

export function ChevronIcon(props: IconProps & { open?: boolean }): ReactNode {
  const { open = false, ...rest } = props;
  return (
    <svg
      {...base(rest)}
      style={{
        transform: open ? "rotate(90deg)" : "rotate(0deg)",
        transition: "transform 120ms",
      }}
    >
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}
