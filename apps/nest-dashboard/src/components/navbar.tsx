"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/agents", label: "Agents" },
  { href: "/experiments", label: "Experiments" },
  { href: "/leaderboard", label: "Leaderboard" },
  { href: "/hackathon", label: "Hackathon" },
  { href: "/visualizer", label: "Visualizer" },
  { href: "/docs", label: "Docs" },
  { href: "/skills", label: "Skills" },
];

export function Navbar() {
  const pathname = usePathname();

  return (
    <nav className="sticky top-0 z-50 border-b border-cream-400/60 bg-cream-100/85 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1240px] items-center justify-between px-6 sm:px-10">
        {/* Wordmark — Nanda Town icon + Nanda Town + "by Project NANDA" + NANDA dots */}
        <Link
          href="/"
          className="flex items-center gap-3 group"
          aria-label="Nanda Town by Project NANDA — home"
        >
          <Image
            src="/brand/nandatown-logo.png"
            alt=""
            width={36}
            height={36}
            priority
            className="h-9 w-9 object-contain"
          />
          <span className="font-display text-[1.4rem] leading-none tracking-tight text-ink-900">
            Nanda Town
          </span>
          <span className="hidden sm:inline-flex items-center gap-2 pl-3 ml-1 border-l border-cream-400 text-[10px] font-mono uppercase tracking-[0.2em] text-ink-300 leading-none">
            by Project NANDA
            <Image
              src="/brand/nanda-logo.png"
              alt="Project NANDA"
              width={18}
              height={18}
              className="h-[18px] w-[18px] object-contain"
            />
          </span>
        </Link>

        {/* Main nav */}
        <div className="hidden md:flex items-center gap-1">
          {links.map((link) => {
            const isActive = pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`relative px-4 py-2 text-[0.92rem] font-medium transition-colors ${
                  isActive
                    ? "text-ink-900"
                    : "text-ink-400 hover:text-ink-900"
                }`}
              >
                {link.label}
                {isActive && (
                  <span className="absolute left-3 right-3 -bottom-px h-px bg-ink-900" />
                )}
              </Link>
            );
          })}
        </div>

        <div className="flex items-center gap-2">
          <a
            href="https://github.com/projnanda/nandatown"
            target="_blank"
            rel="noopener noreferrer"
            className="hidden sm:inline-flex items-center text-[0.85rem] font-medium text-ink-500 hover:text-ink-900 px-3 py-2 transition-colors"
          >
            GitHub
          </a>
        </div>
      </div>
    </nav>
  );
}
