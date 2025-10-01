"""
Content Classification System for SPECTRA
==========================================

Intelligent content analysis and categorization for Telegram messages.
Provides extensible classification pipeline with multiple analysis strategies.
"""
from __future__ import annotations

import re
import mimetypes
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument, MessageMediaContact
from telethon.tl.types import MessageMediaVenue, MessageMediaGeo, MessageMediaPoll, MessageMediaGame
from telethon.tl.types import MessageMediaWebPage, DocumentAttributeFilename, DocumentAttributeVideo
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeSticker, DocumentAttributeAnimated


class ContentType(Enum):
    """Content type enumeration."""
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"
    STICKER = "sticker"
    ANIMATION = "animation"
    CONTACT = "contact"
    LOCATION = "location"
    POLL = "poll"
    GAME = "game"
    WEBPAGE = "webpage"
    TEXT = "text"
    UNKNOWN = "unknown"


class ClassificationStrategy(Enum):
    """Classification strategy enumeration."""
    MEDIA_TYPE = "media_type"
    FILE_EXTENSION = "file_extension"
    CONTENT_ANALYSIS = "content_analysis"
    SIZE_BASED = "size_based"
    SOURCE_BASED = "source_based"
    PATTERN_MATCHING = "pattern_matching"
    ML_CLASSIFICATION = "ml_classification"


@dataclass
class ClassificationRule:
    """Rule for content classification."""
    name: str
    strategy: ClassificationStrategy
    pattern: str
    category: str
    priority: int = 0
    conditions: Dict[str, Any] = field(default_factory=dict)
    metadata_extractors: List[str] = field(default_factory=list)


@dataclass
class ContentMetadata:
    """Metadata extracted from content analysis."""
    content_type: ContentType
    category: str
    subcategory: Optional[str] = None
    file_extension: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    duration: Optional[int] = None
    dimensions: Optional[Tuple[int, int]] = None
    source_channel: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    confidence: float = 1.0
    additional_metadata: Dict[str, Any] = field(default_factory=dict)


class ContentClassifier:
    """
    Intelligent content classification system.

    Analyzes Telegram messages and media to determine appropriate
    categorization for topic organization and routing.
    """

    def __init__(self):
        """Initialize the ContentClassifier."""
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Classification rules (priority-ordered)
        self.rules: List[ClassificationRule] = []

        # File extension mappings
        self.extension_mappings = {
            'image': {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico'},
            'video': {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v'},
            'audio': {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a'},
            'document': {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt'},
            'archive': {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz'},
            'code': {'.py', '.js', '.java', '.c', '.cpp', '.h', '.html', '.css', '.php'},
            'data': {'.json', '.xml', '.csv', '.sql', '.db', '.sqlite'},
            'ebook': {'.epub', '.mobi', '.azw', '.fb2', '.djvu'},
            'font': {'.ttf', '.otf', '.woff', '.woff2', '.eot'},
            'cad': {'.dwg', '.dxf', '.step', '.stp', '.iges', '.igs'},
            'vector': {'.ai', '.eps', '.ps', '.cdr'},
            'executable': {'.exe', '.msi', '.deb', '.rpm', '.dmg', '.app'},
            'iso_image': {'.iso', '.img', '.bin', '.cue'}
        }

        # Content size categories (in bytes)
        self.size_categories = {
            'tiny': (0, 10 * 1024),                    # 0-10KB
            'small': (10 * 1024, 100 * 1024),         # 10-100KB
            'medium': (100 * 1024, 10 * 1024 * 1024), # 100KB-10MB
            'large': (10 * 1024 * 1024, 100 * 1024 * 1024),  # 10-100MB
            'huge': (100 * 1024 * 1024, float('inf'))  # 100MB+
        }

        # Pattern matching rules
        self.text_patterns = {
            'url': re.compile(r'https?://[^\s]+'),
            'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            'hashtag': re.compile(r'#\w+'),
            'mention': re.compile(r'@\w+'),
            'phone': re.compile(r'[\+]?[1-9]?[0-9]{7,15}'),
            'bitcoin': re.compile(r'\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b'),
            'credit_card': re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),
            'ip_address': re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'),
        }

        # Initialize default rules
        self._setup_default_rules()

        self.logger.info("ContentClassifier initialized with default rules")

    def _setup_default_rules(self) -> None:
        """Set up default classification rules."""
        # Media type rules (highest priority)
        self.add_rule(ClassificationRule(
            name="photo_classification",
            strategy=ClassificationStrategy.MEDIA_TYPE,
            pattern="photo",
            category="photos",
            priority=100
        ))

        self.add_rule(ClassificationRule(
            name="video_classification",
            strategy=ClassificationStrategy.MEDIA_TYPE,
            pattern="video",
            category="videos",
            priority=100
        ))

        self.add_rule(ClassificationRule(
            name="audio_classification",
            strategy=ClassificationStrategy.MEDIA_TYPE,
            pattern="audio",
            category="audio",
            priority=100
        ))

        self.add_rule(ClassificationRule(
            name="document_classification",
            strategy=ClassificationStrategy.MEDIA_TYPE,
            pattern="document",
            category="documents",
            priority=90
        ))

        # File extension rules
        self.add_rule(ClassificationRule(
            name="archive_files",
            strategy=ClassificationStrategy.FILE_EXTENSION,
            pattern="archive",
            category="archives",
            priority=80
        ))

        self.add_rule(ClassificationRule(
            name="code_files",
            strategy=ClassificationStrategy.FILE_EXTENSION,
            pattern="code",
            category="source_code",
            priority=80
        ))

        # Size-based rules
        self.add_rule(ClassificationRule(
            name="large_files",
            strategy=ClassificationStrategy.SIZE_BASED,
            pattern="large",
            category="large_files",
            priority=50,
            conditions={'min_size': 50 * 1024 * 1024}  # 50MB
        ))

        # Pattern matching rules
        self.add_rule(ClassificationRule(
            name="url_content",
            strategy=ClassificationStrategy.PATTERN_MATCHING,
            pattern="url",
            category="links",
            priority=60
        ))

    def add_rule(self, rule: ClassificationRule) -> None:
        """Add a classification rule."""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
        self.logger.debug(f"Added classification rule: {rule.name} (priority: {rule.priority})")

    def remove_rule(self, rule_name: str) -> bool:
        """Remove a classification rule by name."""
        for i, rule in enumerate(self.rules):
            if rule.name == rule_name:
                del self.rules[i]
                self.logger.debug(f"Removed classification rule: {rule_name}")
                return True
        return False

    async def classify_message(self, message: Message) -> ContentMetadata:
        """
        Classify a Telegram message and extract metadata.

        Args:
            message: Telegram message to classify

        Returns:
            ContentMetadata: Classification results and extracted metadata
        """
        try:
            # Basic content type detection
            content_type = self._detect_content_type(message)

            # Initialize metadata
            metadata = ContentMetadata(
                content_type=content_type,
                category='general'
            )

            # Extract basic metadata
            await self._extract_basic_metadata(message, metadata)

            # Apply classification rules
            await self._apply_classification_rules(message, metadata)

            # Extract additional metadata based on content type
            await self._extract_type_specific_metadata(message, metadata)

            # Extract keywords and patterns from text
            if message.text:
                self._extract_text_patterns(message.text, metadata)

            self.logger.debug(f"Classified message: {metadata.content_type.value} -> {metadata.category}")
            return metadata

        except Exception as e:
            self.logger.error(f"Error classifying message: {e}")
            return ContentMetadata(
                content_type=ContentType.UNKNOWN,
                category='unknown',
                confidence=0.0
            )

    def _detect_content_type(self, message: Message) -> ContentType:
        """Detect the primary content type of a message."""
        if not message.media:
            return ContentType.TEXT if message.text else ContentType.UNKNOWN

        media = message.media

        if isinstance(media, MessageMediaPhoto):
            return ContentType.PHOTO
        elif isinstance(media, MessageMediaDocument):
            return self._classify_document(media.document)
        elif isinstance(media, MessageMediaContact):
            return ContentType.CONTACT
        elif isinstance(media, (MessageMediaVenue, MessageMediaGeo)):
            return ContentType.LOCATION
        elif isinstance(media, MessageMediaPoll):
            return ContentType.POLL
        elif isinstance(media, MessageMediaGame):
            return ContentType.GAME
        elif isinstance(media, MessageMediaWebPage):
            return ContentType.WEBPAGE

        return ContentType.UNKNOWN

    def _classify_document(self, document) -> ContentType:
        """Classify a document based on its attributes."""
        if not document or not hasattr(document, 'attributes'):
            return ContentType.DOCUMENT

        # Check document attributes
        for attr in document.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                if hasattr(attr, 'round_message') and attr.round_message:
                    return ContentType.VIDEO  # Video message
                return ContentType.VIDEO
            elif isinstance(attr, DocumentAttributeAudio):
                if hasattr(attr, 'voice') and attr.voice:
                    return ContentType.VOICE
                return ContentType.AUDIO
            elif isinstance(attr, DocumentAttributeSticker):
                return ContentType.STICKER
            elif isinstance(attr, DocumentAttributeAnimated):
                return ContentType.ANIMATION

        return ContentType.DOCUMENT

    async def _extract_basic_metadata(self, message: Message, metadata: ContentMetadata) -> None:
        """Extract basic metadata from message."""
        # Source channel information
        if hasattr(message, 'peer_id') and message.peer_id:
            if hasattr(message.peer_id, 'channel_id'):
                metadata.source_channel = str(message.peer_id.channel_id)

        # File-specific metadata
        if message.media and hasattr(message.media, 'document'):
            document = message.media.document
            if document:
                metadata.file_size = getattr(document, 'size', None)
                metadata.mime_type = getattr(document, 'mime_type', None)

                # Extract filename and extension
                for attr in getattr(document, 'attributes', []):
                    if isinstance(attr, DocumentAttributeFilename):
                        filename = attr.file_name
                        metadata.file_extension = Path(filename).suffix.lower()
                        break

                # Extract dimensions for images/videos
                for attr in getattr(document, 'attributes', []):
                    if hasattr(attr, 'w') and hasattr(attr, 'h'):
                        metadata.dimensions = (attr.w, attr.h)
                    if hasattr(attr, 'duration'):
                        metadata.duration = attr.duration

    async def _apply_classification_rules(self, message: Message, metadata: ContentMetadata) -> None:
        """Apply classification rules to determine category."""
        for rule in self.rules:
            if await self._rule_matches(rule, message, metadata):
                metadata.category = rule.category
                metadata.confidence = min(metadata.confidence + 0.1, 1.0)
                self.logger.debug(f"Applied rule: {rule.name} -> {rule.category}")
                return

        # Fallback to content type as category
        metadata.category = metadata.content_type.value

    async def _rule_matches(self, rule: ClassificationRule, message: Message, metadata: ContentMetadata) -> bool:
        """Check if a classification rule matches the message."""
        try:
            if rule.strategy == ClassificationStrategy.MEDIA_TYPE:
                return metadata.content_type.value == rule.pattern

            elif rule.strategy == ClassificationStrategy.FILE_EXTENSION:
                if metadata.file_extension:
                    ext_category = self._get_extension_category(metadata.file_extension)
                    return ext_category == rule.pattern

            elif rule.strategy == ClassificationStrategy.SIZE_BASED:
                if metadata.file_size and rule.conditions:
                    min_size = rule.conditions.get('min_size', 0)
                    max_size = rule.conditions.get('max_size', float('inf'))
                    return min_size <= metadata.file_size <= max_size

            elif rule.strategy == ClassificationStrategy.PATTERN_MATCHING:
                if message.text and rule.pattern in self.text_patterns:
                    pattern = self.text_patterns[rule.pattern]
                    return bool(pattern.search(message.text))

            elif rule.strategy == ClassificationStrategy.CONTENT_ANALYSIS:
                # Placeholder for advanced content analysis
                return await self._analyze_content(message, rule)

            elif rule.strategy == ClassificationStrategy.SOURCE_BASED:
                return metadata.source_channel == rule.pattern

        except Exception as e:
            self.logger.warning(f"Error applying rule {rule.name}: {e}")

        return False

    def _get_extension_category(self, extension: str) -> Optional[str]:
        """Get category for file extension."""
        for category, extensions in self.extension_mappings.items():
            if extension in extensions:
                return category
        return None

    async def _analyze_content(self, message: Message, rule: ClassificationRule) -> bool:
        """Placeholder for advanced content analysis."""
        # This could be extended with ML-based classification,
        # OCR for images, speech-to-text for audio, etc.
        return False

    async def _extract_type_specific_metadata(self, message: Message, metadata: ContentMetadata) -> None:
        """Extract metadata specific to content type."""
        if metadata.content_type == ContentType.PHOTO:
            await self._extract_photo_metadata(message, metadata)
        elif metadata.content_type == ContentType.VIDEO:
            await self._extract_video_metadata(message, metadata)
        elif metadata.content_type == ContentType.AUDIO:
            await self._extract_audio_metadata(message, metadata)
        elif metadata.content_type == ContentType.DOCUMENT:
            await self._extract_document_metadata(message, metadata)

    async def _extract_photo_metadata(self, message: Message, metadata: ContentMetadata) -> None:
        """Extract photo-specific metadata."""
        metadata.subcategory = 'photo'
        if metadata.file_size:
            size_category = self._get_size_category(metadata.file_size)
            metadata.additional_metadata['size_category'] = size_category

    async def _extract_video_metadata(self, message: Message, metadata: ContentMetadata) -> None:
        """Extract video-specific metadata."""
        metadata.subcategory = 'video'
        if metadata.duration:
            if metadata.duration < 30:
                metadata.subcategory = 'short_video'
            elif metadata.duration > 3600:
                metadata.subcategory = 'long_video'

    async def _extract_audio_metadata(self, message: Message, metadata: ContentMetadata) -> None:
        """Extract audio-specific metadata."""
        if metadata.content_type == ContentType.VOICE:
            metadata.subcategory = 'voice_message'
        else:
            metadata.subcategory = 'audio_file'

    async def _extract_document_metadata(self, message: Message, metadata: ContentMetadata) -> None:
        """Extract document-specific metadata."""
        if metadata.file_extension:
            ext_category = self._get_extension_category(metadata.file_extension)
            if ext_category:
                metadata.subcategory = ext_category
                metadata.additional_metadata['file_type'] = ext_category

    def _extract_text_patterns(self, text: str, metadata: ContentMetadata) -> None:
        """Extract patterns and keywords from text content."""
        keywords = []

        # Extract pattern matches
        for pattern_name, pattern in self.text_patterns.items():
            matches = pattern.findall(text)
            if matches:
                keywords.append(pattern_name)
                metadata.additional_metadata[f'{pattern_name}_count'] = len(matches)

        # Simple keyword extraction (could be enhanced with NLP)
        words = re.findall(r'\b\w{3,}\b', text.lower())
        common_words = {'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'who', 'boy', 'did', 'man', 'end', 'few', 'got', 'let', 'put', 'say', 'she', 'too', 'use'}
        keywords.extend([word for word in set(words) if word not in common_words and len(word) > 3])

        metadata.keywords = keywords[:20]  # Limit to 20 keywords

    def _get_size_category(self, size: int) -> str:
        """Get size category for file size."""
        for category, (min_size, max_size) in self.size_categories.items():
            if min_size <= size < max_size:
                return category
        return 'unknown'

    def get_classification_stats(self) -> Dict[str, Any]:
        """Get classification statistics."""
        return {
            'total_rules': len(self.rules),
            'rule_strategies': [rule.strategy.value for rule in self.rules],
            'extension_categories': len(self.extension_mappings),
            'text_patterns': len(self.text_patterns)
        }

    def export_rules(self) -> List[Dict[str, Any]]:
        """Export classification rules for configuration."""
        return [
            {
                'name': rule.name,
                'strategy': rule.strategy.value,
                'pattern': rule.pattern,
                'category': rule.category,
                'priority': rule.priority,
                'conditions': rule.conditions,
                'metadata_extractors': rule.metadata_extractors
            }
            for rule in self.rules
        ]

    def import_rules(self, rules_data: List[Dict[str, Any]]) -> None:
        """Import classification rules from configuration."""
        for rule_data in rules_data:
            try:
                rule = ClassificationRule(
                    name=rule_data['name'],
                    strategy=ClassificationStrategy(rule_data['strategy']),
                    pattern=rule_data['pattern'],
                    category=rule_data['category'],
                    priority=rule_data.get('priority', 0),
                    conditions=rule_data.get('conditions', {}),
                    metadata_extractors=rule_data.get('metadata_extractors', [])
                )
                self.add_rule(rule)
            except Exception as e:
                self.logger.error(f"Failed to import rule {rule_data.get('name', 'unknown')}: {e}")

    async def batch_classify(self, messages: List[Message]) -> List[ContentMetadata]:
        """Classify multiple messages in batch."""
        results = []
        for message in messages:
            try:
                metadata = await self.classify_message(message)
                results.append(metadata)
            except Exception as e:
                self.logger.error(f"Failed to classify message {message.id}: {e}")
                results.append(ContentMetadata(
                    content_type=ContentType.UNKNOWN,
                    category='unknown',
                    confidence=0.0
                ))
        return results