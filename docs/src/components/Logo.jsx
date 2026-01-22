import React from 'react';
import useBaseUrl from '@docusaurus/useBaseUrl';

export default function Logo({ size = 'medium' }) {
  const logoUrl = useBaseUrl('/img/SPECTRA.png');
  
  const sizeClasses = {
    small: { width: '32px', height: '32px' },
    medium: { width: '48px', height: '48px' },
    large: { width: '120px', height: '120px' },
  };

  return (
    <img
      src={logoUrl}
      alt="SPECTRA Logo"
      style={{
        ...sizeClasses[size],
        objectFit: 'contain',
      }}
    />
  );
}
