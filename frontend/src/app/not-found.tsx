import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50 px-4 text-center text-slate-800">
      <h1 className="text-2xl font-bold">Page not found</h1>
      <p className="max-w-md text-sm text-slate-600">The page you are looking for does not exist or has moved.</p>
      <Link href="/" className="rounded-lg bg-sky-700 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">
        Back to map
      </Link>
    </main>
  );
}
