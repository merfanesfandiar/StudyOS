import Link from "next/link";

export default function NotFound() {
  return (
    <main className="grid min-h-screen place-items-center px-6" id="main-content">
      <div className="text-center">
        <p className="text-sm font-bold uppercase tracking-widest text-indigo-600">404</p>
        <h1 className="mt-3 text-3xl font-bold">Page not found</h1>
        <p className="mt-3 text-slate-600">The page you requested does not exist.</p>
        <Link className="btn-primary mt-7" href="/dashboard">
          Return to dashboard
        </Link>
      </div>
    </main>
  );
}
