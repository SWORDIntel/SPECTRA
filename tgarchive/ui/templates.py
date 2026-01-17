"""Templates and presets system for SPECTRA operations"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TemplateManager:
    """Manages operation templates and presets"""
    
    def __init__(self, templates_dir: Optional[Path] = None):
        if templates_dir is None:
            templates_dir = Path("data/templates")
        self.templates_dir = templates_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.templates: Dict[str, Dict[str, Any]] = {}
        self._load_templates()
    
    def _load_templates(self):
        """Load templates from directory"""
        for template_file in self.templates_dir.glob("*.json"):
            try:
                with open(template_file, 'r', encoding='utf-8') as f:
                    template = json.load(f)
                    name = template.get("name", template_file.stem)
                    self.templates[name] = template
            except Exception as e:
                logger.warning(f"Failed to load template {template_file}: {e}")
    
    def save_template(self, name: str, template_data: Dict[str, Any]):
        """Save a template"""
        template_data["name"] = name
        template_file = self.templates_dir / f"{name}.json"
        try:
            with open(template_file, 'w', encoding='utf-8') as f:
                json.dump(template_data, f, indent=2, ensure_ascii=False)
            self.templates[name] = template_data
            logger.debug(f"Saved template: {name}")
        except Exception as e:
            logger.error(f"Failed to save template {name}: {e}")
    
    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a template by name"""
        return self.templates.get(name)
    
    def list_templates(self) -> List[str]:
        """List all template names"""
        return list(self.templates.keys())
    
    def delete_template(self, name: str) -> bool:
        """Delete a template"""
        template_file = self.templates_dir / f"{name}.json"
        if template_file.exists():
            template_file.unlink()
            self.templates.pop(name, None)
            return True
        return False
