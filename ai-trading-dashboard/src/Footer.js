import React from "react";

function Footer() {
  return (
    <footer className="app-footer">
      <div className="footer-content">
        <div className="footer-brand">
          <span className="logo-bold">VISION</span> <span className="logo-light">AI</span>
          <span className="footer-copy"> © 2026</span>
        </div>
        
        <div className="footer-credit">
          Made by <strong>Abhinav Saha</strong>
        </div>
        
        <div className="footer-links">
          <a href="https://github.com/abhinavsaha24" target="_blank" rel="noreferrer">
            GitHub
          </a>
          <a href="https://linkedin.com/in/abhinavsaha24" target="_blank" rel="noreferrer">
            LinkedIn
          </a>
          <a href="mailto:abhinavsaha24@gmail.com">
            Contact Email
          </a>
        </div>
      </div>
    </footer>
  );
}

export default Footer;
