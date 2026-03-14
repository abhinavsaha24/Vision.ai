import React from 'react';

export default function Footer() {
  return (
    <footer className="w-full bg-black py-6 mt-8 border-t border-slate-800 text-center">
      <div className="container mx-auto px-4 flex flex-col items-center justify-center space-y-2">
        <div className="text-gray-400 font-mono tracking-wider">Made by Abhinav Saha</div>
        <div className="flex items-center space-x-6 text-sm font-mono text-gray-500">
          <a href="#" className="hover:text-gray-300 transition-colors duration-200">LinkedIn</a>
          <span className="text-slate-700">|</span>
          <a href="#" className="hover:text-gray-300 transition-colors duration-200">GitHub</a>
          <span className="text-slate-700">|</span>
          <a href="#" className="hover:text-gray-300 transition-colors duration-200">Email</a>
        </div>
        <div className="text-gray-500 text-xs font-mono tracking-widest mt-4">© 2026 Vision AI</div>
      </div>
    </footer>
  );
}
