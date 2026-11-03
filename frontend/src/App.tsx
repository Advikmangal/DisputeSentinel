const navigation = ['Dashboard', 'Payments', 'Evidence Vault', 'Dispute Agent']

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-6 sm:px-12">
        <div className="mx-auto max-w-5xl">
          <p className="text-xs font-semibold tracking-widest text-teal-300">PAYPAL SANDBOX</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">DisputeSentinel</h1>
          <nav aria-label="Main navigation" className="mt-6">
            <ul className="flex flex-wrap gap-3">
              {navigation.map((item) => (
                <li key={item}>
                  <button
                    type="button"
                    disabled
                    className="cursor-not-allowed rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300"
                  >
                    {item}
                  </button>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-16 sm:px-12">
        <p className="text-sm font-medium text-teal-300">Project scaffold</p>
        <h2 className="mt-3 text-2xl font-semibold">Payment evidence and dispute management</h2>
        <p className="mt-4 max-w-xl leading-relaxed text-slate-400">
          Dashboard, Payments, Evidence Vault, and Dispute Agent are coming soon.
          Navigation is a placeholder while these screens are built.
        </p>
      </main>
    </div>
  )
}
