import React from 'react';

export default function Footer() {
  return (
    <footer style={{ padding: '16px', marginTop: '20px' }} className="w-full bg-[#020617] border-t border-dark-border text-center flex flex-col items-center justify-center space-y-2">
      <div className="container mx-auto px-4 flex flex-col items-center justify-center space-y-3">
        <div className="text-dark-muted font-mono tracking-wider">Made by Abhinav Saha</div>
        <div className="flex items-center space-x-6 text-sm font-mono text-dark-muted">
          <a href="#" className="hover:text-white transition-colors duration-200">LinkedIn</a>
          <span className="text-dark-border">|</span>
          <a href="#" className="hover:text-white transition-colors duration-200">GitHub</a>
          <span className="text-dark-border">|</span>
          <a href="#" className="hover:text-white transition-colors duration-200">Email</a>
        </div>
        <div className="text-dark-muted text-xs font-mono tracking-widest mt-4">© 2026 Vision AI</div>
      </div>
    </footer>
  );
}
