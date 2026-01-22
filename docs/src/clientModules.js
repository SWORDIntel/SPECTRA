// Force dark theme on all pages - AGGRESSIVE ENFORCEMENT
import ExecutionEnvironment from '@docusaurus/ExecutionEnvironment';

if (ExecutionEnvironment.canUseDOM) {
  // Force dark theme immediately on page load
  const forceDarkTheme = () => {
    // Set data-theme attribute - THIS IS CRITICAL
    document.documentElement.setAttribute('data-theme', 'dark');
    
    // Remove light theme classes
    document.documentElement.classList.remove('light-theme');
    document.documentElement.classList.remove('theme-light');
    document.documentElement.classList.add('dark-theme');
    document.documentElement.classList.add('theme-dark');
    
    // Set color-scheme CSS property
    document.documentElement.style.colorScheme = 'dark';
    
    // Override localStorage to prevent light theme
    try {
      localStorage.setItem('theme', 'dark');
      localStorage.setItem('docusaurus-theme', 'dark');
      localStorage.setItem('theme-preference', 'dark');
      // Remove any light theme preferences
      localStorage.removeItem('theme-light');
      localStorage.removeItem('light-theme');
    } catch (e) {
      // Ignore localStorage errors
    }
    
    // Also set on body if it exists
    if (document.body) {
      document.body.setAttribute('data-theme', 'dark');
      document.body.classList.remove('light-theme', 'theme-light');
      document.body.classList.add('dark-theme', 'theme-dark');
    }
  };
  
  // Run immediately - BEFORE anything else
  forceDarkTheme();
  
  // Run as early as possible
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', forceDarkTheme, {once: true});
  } else {
    // DOM already loaded, run immediately
    setTimeout(forceDarkTheme, 0);
  }
  
  // Also run after a short delay to catch any late theme changes
  setTimeout(forceDarkTheme, 10);
  setTimeout(forceDarkTheme, 100);
  setTimeout(forceDarkTheme, 500);
  
  // Watch for theme changes and force dark - AGGRESSIVE
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.type === 'attributes') {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        if (currentTheme !== 'dark') {
          forceDarkTheme();
        }
        // Also check classes
        if (document.documentElement.classList.contains('light-theme') || 
            document.documentElement.classList.contains('theme-light')) {
          forceDarkTheme();
        }
      }
    });
  });
  
  // Observe document element for theme changes
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme', 'class', 'style'],
    childList: false,
    subtree: false
  });
  
  // Also observe body if it exists
  if (document.body) {
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ['data-theme', 'class'],
      childList: false,
      subtree: false
    });
  }
  
  // Intercept theme changes on documentElement specifically
  const originalSetAttribute = document.documentElement.setAttribute.bind(document.documentElement);
  document.documentElement.setAttribute = function(name, value) {
    if (name === 'data-theme' && value !== 'dark') {
      // Force dark theme - prevent any light theme from being set
      originalSetAttribute('data-theme', 'dark');
      return;
    }
    originalSetAttribute(name, value);
  };
  
  // Also intercept on body
  if (document.body) {
    const bodySetAttribute = document.body.setAttribute.bind(document.body);
    document.body.setAttribute = function(name, value) {
      if (name === 'data-theme' && value !== 'dark') {
        bodySetAttribute('data-theme', 'dark');
        return;
      }
      bodySetAttribute(name, value);
    };
  }
}
