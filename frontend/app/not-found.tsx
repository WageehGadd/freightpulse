"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Compass, Home, ArrowLeft } from "lucide-react";

export default function NotFound() {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <div className="flex min-h-[80vh] flex-col items-center justify-center text-center px-4 py-12 bg-gradient-to-b from-sky-50/40 via-white to-slate-50/30">
      <div className="mx-auto flex flex-col items-center max-w-lg">
        {/* Top Icon Badge */}
        <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-white border border-slate-100 shadow-md shadow-blue-500/5">
          <Compass className="h-8 w-8 text-blue-600 stroke-[2.2]" />
        </div>

        {/* Subtitle */}
        <span className="text-xs font-bold tracking-widest text-blue-600 uppercase">
          ROUTE NOT FOUND
        </span>

        {/* Huge 404 Heading */}
        <h1 className="mt-2 text-7xl font-extrabold tracking-tight text-slate-900 sm:text-8xl">
          404
        </h1>

        {/* Main Heading */}
        <h2 className="mt-3 text-2xl font-bold text-slate-900 sm:text-3xl">
          This route drifted off course.
        </h2>

        {/* Description Paragraph */}
        <p className="mt-4 text-sm sm:text-base text-slate-500 leading-relaxed">
          We couldn&apos;t find{" "}
          <code className="rounded-md border border-slate-200/80 bg-slate-100/90 px-2 py-0.5 font-mono text-xs font-medium text-slate-700">
            {pathname || "/unknown"}
          </code>
          . Let&apos;s get you back to the intelligence that matters.
        </p>

        {/* Action Buttons */}
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link
            href="/"
            className="inline-flex items-center gap-2 rounded-xl bg-[#0066ff] px-5 py-2.5 text-sm font-semibold text-white shadow-xs hover:bg-blue-600 transition-colors"
          >
            <Home className="h-4 w-4" />
            Back to dashboard
          </Link>

          <button
            onClick={() => router.back()}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 shadow-xs hover:bg-slate-50 transition-colors cursor-pointer"
          >
            <ArrowLeft className="h-4 w-4 text-slate-500" />
            Go back
          </button>
        </div>
      </div>
    </div>
  );
}
