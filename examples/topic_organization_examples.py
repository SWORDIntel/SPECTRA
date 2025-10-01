"""
SPECTRA Topic Organization Examples
===================================

Example usage scenarios and testing scripts for the topic organization system.
Demonstrates various features and use cases of the intelligent content routing.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List

# Configure logging for examples
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Example imports (adjust paths as needed)
from tgarchive.config_models import Config
from tgarchive.db import SpectraDB
from tgarchive.forwarding.enhanced_forwarder import EnhancedAttachmentForwarder
from tgarchive.forwarding.organization_engine import (
    OrganizationEngine, OrganizationConfig, OrganizationMode
)
from tgarchive.forwarding.topic_manager import TopicCreationStrategy
from tgarchive.forwarding.content_classifier import ContentClassifier, ClassificationRule, ClassificationStrategy


class TopicOrganizationExamples:
    """Examples and testing scenarios for topic organization."""

    def __init__(self, config_path: str = "spectra_config.json", db_path: str = "spectra.db"):
        """Initialize examples with configuration and database."""
        self.config = Config(Path(config_path))
        self.db = SpectraDB(Path(db_path))
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def example_1_basic_content_classification(self):
        """
        Example 1: Basic Content Classification

        Demonstrates how to use the ContentClassifier to analyze
        different types of Telegram messages.
        """
        self.logger.info("=== Example 1: Basic Content Classification ===")

        # Initialize classifier
        classifier = ContentClassifier()

        # Simulate different message types (in real usage, these would be Telegram Message objects)
        mock_messages = [
            self._create_mock_message("photo", "A beautiful sunset photo", file_size=1024*1024),
            self._create_mock_message("video", "Funny cat video", file_size=5*1024*1024, duration=30),
            self._create_mock_message("document", "Report.pdf", file_size=2*1024*1024, filename="quarterly_report.pdf"),
            self._create_mock_message("text", "Check out this link: https://example.com"),
            self._create_mock_message("audio", "Voice message", file_size=500*1024, duration=15),
        ]

        # Classify each message
        for i, message in enumerate(mock_messages):
            try:
                metadata = await classifier.classify_message(message)
                self.logger.info(f"Message {i+1}:")
                self.logger.info(f"  Content Type: {metadata.content_type.value}")
                self.logger.info(f"  Category: {metadata.category}")
                self.logger.info(f"  Subcategory: {metadata.subcategory}")
                self.logger.info(f"  Confidence: {metadata.confidence:.2f}")
                if metadata.keywords:
                    self.logger.info(f"  Keywords: {', '.join(metadata.keywords[:5])}")
                self.logger.info("")
            except Exception as e:
                self.logger.error(f"Classification error for message {i+1}: {e}")

    async def example_2_custom_classification_rules(self):
        """
        Example 2: Custom Classification Rules

        Shows how to create and apply custom classification rules
        for specialized content organization.
        """
        self.logger.info("=== Example 2: Custom Classification Rules ===")

        classifier = ContentClassifier()

        # Add custom rules for different scenarios

        # Rule 1: Large files go to a separate category
        large_files_rule = ClassificationRule(
            name="large_files_separator",
            strategy=ClassificationStrategy.SIZE_BASED,
            pattern="large",
            category="large_files",
            priority=90,
            conditions={'min_size': 10 * 1024 * 1024}  # 10MB
        )
        classifier.add_rule(large_files_rule)

        # Rule 2: Source code files
        code_files_rule = ClassificationRule(
            name="source_code_detector",
            strategy=ClassificationStrategy.FILE_EXTENSION,
            pattern="code",
            category="programming",
            priority=80
        )
        classifier.add_rule(code_files_rule)

        # Rule 3: URLs in messages go to links category
        url_rule = ClassificationRule(
            name="url_detector",
            strategy=ClassificationStrategy.PATTERN_MATCHING,
            pattern="url",
            category="links",
            priority=70
        )
        classifier.add_rule(url_rule)

        self.logger.info(f"Added {len(classifier.rules)} classification rules")

        # Test with various content types
        test_cases = [
            self._create_mock_message("document", "Large video file", file_size=50*1024*1024, filename="movie.mp4"),
            self._create_mock_message("document", "Python script", filename="main.py", file_size=1024),
            self._create_mock_message("text", "Check this out: https://github.com/example/repo"),
            self._create_mock_message("photo", "Small image", file_size=100*1024),
        ]

        for i, message in enumerate(test_cases):
            metadata = await classifier.classify_message(message)
            self.logger.info(f"Test case {i+1}: {metadata.category} (confidence: {metadata.confidence:.2f})")

    async def example_3_topic_manager_usage(self):
        """
        Example 3: Topic Manager Usage

        Demonstrates how to use TopicManager to create and manage
        forum topics based on content analysis.
        """
        self.logger.info("=== Example 3: Topic Manager Usage ===")

        # Note: This example requires a real Telegram client and channel
        # In actual usage, you would have:
        # from tgarchive.forwarding.client import ClientManager
        # client_manager = ClientManager(self.config)
        # client = await client_manager.get_client()

        # For demonstration, we'll show the configuration and logic

        channel_id = 1234567890  # Example channel ID

        # Different topic creation strategies
        strategies_to_test = [
            TopicCreationStrategy.CONTENT_TYPE,
            TopicCreationStrategy.DATE_BASED,
            TopicCreationStrategy.FILE_EXTENSION,
        ]

        for strategy in strategies_to_test:
            self.logger.info(f"Testing strategy: {strategy.value}")

            # Example content metadata for different strategies
            if strategy == TopicCreationStrategy.CONTENT_TYPE:
                test_metadata = [
                    {'content_type': 'photo', 'category': 'photos'},
                    {'content_type': 'video', 'category': 'videos'},
                    {'content_type': 'document', 'category': 'documents'},
                ]
            elif strategy == TopicCreationStrategy.DATE_BASED:
                from datetime import datetime
                today = datetime.now()
                test_metadata = [
                    {'content_type': 'general', 'category': 'daily', 'date': today.strftime('%Y-%m-%d')},
                ]
            elif strategy == TopicCreationStrategy.FILE_EXTENSION:
                test_metadata = [
                    {'file_extension': '.pdf', 'category': 'pdf_files'},
                    {'file_extension': '.zip', 'category': 'archives'},
                    {'file_extension': '.py', 'category': 'source_code'},
                ]

            for metadata in test_metadata:
                # This would normally create actual topics
                self.logger.info(f"  Would create topic for: {metadata}")

        self.logger.info("Topic manager examples completed (simulation mode)")

    async def example_4_organization_engine_workflow(self):
        """
        Example 4: Organization Engine Workflow

        Shows the complete workflow of message organization including
        content classification, topic determination, and statistics.
        """
        self.logger.info("=== Example 4: Organization Engine Workflow ===")

        # Configuration for different organization modes
        configs_to_test = [
            OrganizationConfig(
                mode=OrganizationMode.AUTO_CREATE,
                topic_strategy=TopicCreationStrategy.CONTENT_TYPE,
                enable_content_analysis=True,
                debug_mode=True
            ),
            OrganizationConfig(
                mode=OrganizationMode.EXISTING_ONLY,
                topic_strategy=TopicCreationStrategy.DATE_BASED,
                enable_content_analysis=True,
                classification_confidence_threshold=0.8
            ),
            OrganizationConfig(
                mode=OrganizationMode.HYBRID,
                topic_strategy=TopicCreationStrategy.HYBRID,
                enable_content_analysis=True,
                auto_cleanup_empty_topics=True
            )
        ]

        channel_id = 1234567890  # Example channel ID

        for i, config in enumerate(configs_to_test):
            self.logger.info(f"Testing configuration {i+1}: {config.mode.value}")

            # In real usage, you would initialize like this:
            # organization_engine = OrganizationEngine(client, channel_id, config, self.db)
            # await organization_engine.initialize()

            # Simulate processing different message types
            message_scenarios = [
                "High-resolution photo from vacation",
                "Important business document (PDF)",
                "Funny video compilation",
                "Voice message with instructions",
                "Link to interesting article",
            ]

            for scenario in message_scenarios:
                # This would normally process real messages
                self.logger.info(f"  Processing: {scenario}")
                # result = await organization_engine.organize_message(mock_message)
                # self.logger.info(f"    → Topic: {result.topic_title}, Fallback: {result.fallback_used}")

            # Show statistics (simulated)
            stats = {
                'messages_processed': len(message_scenarios),
                'successful_assignments': 4,
                'fallback_used': 1,
                'success_rate': 0.8
            }
            self.logger.info(f"  Statistics: {stats}")
            self.logger.info("")

    async def example_5_enhanced_forwarder_integration(self):
        """
        Example 5: Enhanced Forwarder Integration

        Demonstrates how to use the EnhancedAttachmentForwarder with
        topic organization for complete message forwarding with routing.
        """
        self.logger.info("=== Example 5: Enhanced Forwarder Integration ===")

        # Create organization configuration
        org_config = OrganizationConfig(
            mode=OrganizationMode.AUTO_CREATE,
            topic_strategy=TopicCreationStrategy.CONTENT_TYPE,
            enable_content_analysis=True,
            enable_statistics=True,
            debug_mode=True
        )

        # Initialize enhanced forwarder (simulation)
        # In real usage:
        # forwarder = EnhancedAttachmentForwarder(
        #     config=self.config,
        #     db=self.db,
        #     enable_topic_organization=True,
        #     organization_config=org_config
        # )

        self.logger.info("Enhanced forwarder configuration:")
        self.logger.info(f"  Organization Mode: {org_config.mode.value}")
        self.logger.info(f"  Topic Strategy: {org_config.topic_strategy.value}")
        self.logger.info(f"  Content Analysis: {org_config.enable_content_analysis}")
        self.logger.info(f"  Statistics: {org_config.enable_statistics}")

        # Simulate forwarding workflow
        forwarding_scenarios = [
            {
                "origin": "@source_channel",
                "destination": "@organized_forum",
                "description": "Forward tech news with automatic categorization"
            },
            {
                "origin": "@media_channel",
                "destination": "@media_archive",
                "description": "Forward media files with type-based topics"
            },
            {
                "origin": "@documents_channel",
                "destination": "@document_library",
                "description": "Forward documents with extension-based organization"
            }
        ]

        for scenario in forwarding_scenarios:
            self.logger.info(f"Forwarding scenario: {scenario['description']}")
            self.logger.info(f"  {scenario['origin']} → {scenario['destination']}")

            # Simulate statistics
            stats = {
                "messages_forwarded": 25,
                "topics_created": 3,
                "topic_assignments": 20,
                "fallback_used": 5,
                "success_rate": "80%"
            }

            self.logger.info(f"  Results: {stats}")
            self.logger.info("")

    async def example_6_database_integration_and_analytics(self):
        """
        Example 6: Database Integration and Analytics

        Shows how to use the database operations for topic tracking,
        statistics, and analytics.
        """
        self.logger.info("=== Example 6: Database Integration and Analytics ===")

        # In real usage, you would use TopicOperations
        # from tgarchive.db.topic_operations import TopicOperations
        # topic_ops = TopicOperations(str(self.db.db_path))

        # Simulate database operations
        channel_id = 1234567890

        # Example statistics queries (simulated results)
        simulated_efficiency = {
            'total_messages_processed': 1500,
            'success_rate_percent': 85.5,
            'fallback_rate_percent': 14.5,
            'topics_created': 12,
            'avg_messages_per_day': 50.0
        }

        simulated_topic_performance = [
            {'topic_id': 1, 'title': '📸 Photos', 'category': 'photos', 'total_assignments': 450, 'avg_confidence': 0.95},
            {'topic_id': 2, 'title': '📄 Documents', 'category': 'documents', 'total_assignments': 300, 'avg_confidence': 0.88},
            {'topic_id': 3, 'title': '🎬 Videos', 'category': 'videos', 'total_assignments': 250, 'avg_confidence': 0.92},
            {'topic_id': 4, 'title': '💻 Source Code', 'category': 'source_code', 'total_assignments': 180, 'avg_confidence': 0.91},
            {'topic_id': 5, 'title': '📦 Archives', 'category': 'archives', 'total_assignments': 150, 'avg_confidence': 0.89},
        ]

        simulated_categories = {
            'photos': 450,
            'documents': 300,
            'videos': 250,
            'source_code': 180,
            'archives': 150,
            'audio': 120,
            'links': 50
        }

        # Display analytics
        self.logger.info("Organization Efficiency Report:")
        for key, value in simulated_efficiency.items():
            self.logger.info(f"  {key}: {value}")

        self.logger.info("\nTop Performing Topics:")
        for topic in simulated_topic_performance:
            self.logger.info(
                f"  {topic['title']} ({topic['category']}): "
                f"{topic['total_assignments']} messages, "
                f"{topic['avg_confidence']:.2f} confidence"
            )

        self.logger.info("\nCategory Distribution:")
        for category, count in simulated_categories.items():
            percentage = (count / sum(simulated_categories.values())) * 100
            self.logger.info(f"  {category}: {count} ({percentage:.1f}%)")

    def _create_mock_message(self, content_type: str, text: str = "", **kwargs):
        """Create a mock message for testing (replace with actual Message objects in production)."""
        class MockMessage:
            def __init__(self, content_type, text, **kwargs):
                self.id = kwargs.get('id', 12345)
                self.text = text
                self.date = kwargs.get('date')
                self.file_size = kwargs.get('file_size')
                self.filename = kwargs.get('filename')
                self.duration = kwargs.get('duration')
                self.media = content_type != 'text'

                # Create mock media based on content type
                if content_type == 'photo':
                    self.media = MockPhotoMedia()
                elif content_type == 'video':
                    self.media = MockVideoMedia(duration=kwargs.get('duration', 30))
                elif content_type == 'document':
                    self.media = MockDocumentMedia(filename=kwargs.get('filename', 'file.txt'))
                elif content_type == 'audio':
                    self.media = MockAudioMedia(duration=kwargs.get('duration', 60))
                elif content_type == 'text':
                    self.media = None

        class MockPhotoMedia:
            def __init__(self):
                self.photo = True

        class MockVideoMedia:
            def __init__(self, duration=30):
                self.document = MockDocument('video/mp4', duration=duration)

        class MockDocumentMedia:
            def __init__(self, filename='file.txt'):
                self.document = MockDocument('application/octet-stream', filename=filename)

        class MockAudioMedia:
            def __init__(self, duration=60):
                self.document = MockDocument('audio/mp3', duration=duration)

        class MockDocument:
            def __init__(self, mime_type, **kwargs):
                self.mime_type = mime_type
                self.size = kwargs.get('size', 1024)
                self.attributes = []

                if 'filename' in kwargs:
                    self.attributes.append(MockFilenameAttribute(kwargs['filename']))
                if 'duration' in kwargs:
                    if 'video' in mime_type:
                        self.attributes.append(MockVideoAttribute(kwargs['duration']))
                    elif 'audio' in mime_type:
                        self.attributes.append(MockAudioAttribute(kwargs['duration']))

        class MockFilenameAttribute:
            def __init__(self, filename):
                self.file_name = filename

        class MockVideoAttribute:
            def __init__(self, duration):
                self.duration = duration
                self.w = 1920
                self.h = 1080

        class MockAudioAttribute:
            def __init__(self, duration):
                self.duration = duration
                self.voice = False

        return MockMessage(content_type, text, **kwargs)

    async def run_all_examples(self):
        """Run all examples in sequence."""
        examples = [
            self.example_1_basic_content_classification,
            self.example_2_custom_classification_rules,
            self.example_3_topic_manager_usage,
            self.example_4_organization_engine_workflow,
            self.example_5_enhanced_forwarder_integration,
            self.example_6_database_integration_and_analytics,
        ]

        self.logger.info("SPECTRA Topic Organization Examples")
        self.logger.info("=" * 50)

        for example in examples:
            try:
                await example()
                self.logger.info("")
            except Exception as e:
                self.logger.error(f"Error in example {example.__name__}: {e}")

        self.logger.info("All examples completed!")


async def main():
    """Main function to run examples."""
    examples = TopicOrganizationExamples()
    await examples.run_all_examples()


# CLI Usage Examples
def print_cli_usage_examples():
    """Print command-line usage examples."""
    print("""
SPECTRA Topic Organization CLI Usage Examples
==============================================

1. Basic forwarding with topic organization:
   python -m tgarchive forward --origin @source_channel --destination @forum_channel \\
       --enable-topic-organization --topic-strategy content_type

2. Forwarding with custom organization settings:
   python -m tgarchive forward --origin @media_channel --destination @organized_forum \\
       --organization-mode auto_create --fallback-strategy general_topic \\
       --max-topics-per-channel 50 --topic-creation-cooldown 60

3. Forwarding with file extension-based topics:
   python -m tgarchive forward --origin @files_channel --destination @file_archive \\
       --topic-strategy file_extension --classification-confidence-threshold 0.8

4. Date-based organization for daily archives:
   python -m tgarchive forward --origin @news_channel --destination @daily_archive \\
       --topic-strategy date_based --general-topic-title "Daily News"

5. List topics in a forum channel:
   python -m tgarchive topics list --channel @organized_forum --active-only

6. Create a custom topic:
   python -m tgarchive topics create --channel @forum --title "📚 Research Papers" \\
       --category research --icon-color "#3498db"

7. View organization statistics:
   python -m tgarchive topics stats --channel @organized_forum --days 30

8. Generate organization report:
   python -m tgarchive topics report --channel @forum --days 7 --format json \\
       --output organization_report.json

9. Configure topic organization:
   python -m tgarchive topics config set --channel @forum --mode hybrid \\
       --strategy content_type --max-topics 75

10. Clean up empty topics:
    python -m tgarchive topics cleanup --channel @forum --min-age-hours 48 --dry-run

Configuration Examples in spectra_config.json:
==============================================

{
  "topic_organization": {
    "enabled": true,
    "mode": "auto_create",
    "topic_strategy": "content_type",
    "fallback_strategy": "general_topic",
    "max_topics_per_channel": 100,
    "topic_creation_cooldown_seconds": 30,
    "enable_content_analysis": true,
    "classification_confidence_threshold": 0.7,
    "general_topic_title": "General Discussion",
    "auto_cleanup_empty_topics": false,
    "enable_statistics": true
  }
}
""")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--cli-examples":
        print_cli_usage_examples()
    else:
        asyncio.run(main())