export function Footer() {
  return (
    <footer className="w-full bg-black border-t border-slate-800/50 py-6 mt-auto shrink-0">
      <div className="container mx-auto px-4 flex flex-col items-center justify-center gap-2 text-center">
        <p className="text-sm font-medium text-slate-300">
          Made by Abhinav Saha
        </p>
        <div className="flex items-center gap-4 text-xs text-slate-400">
          <a href="#" className="hover:text-indigo-400 transition-colors">LinkedIn</a>
          <span className="text-slate-700">|</span>
          <a href="#" className="hover:text-indigo-400 transition-colors">GitHub</a>
          <span className="text-slate-700">|</span>
          <a href="mailto:contact@example.com" className="hover:text-indigo-400 transition-colors">Email</a>
        </div>
        <p className="text-[10px] text-slate-500 font-mono mt-1">
          &copy; 2026 Vision AI
        </p>
      </div>
    </footer>
  );
}
