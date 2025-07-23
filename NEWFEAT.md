JULES TASK LIST: SPECTRA Forwarding & Scheduling System
Core Forwarding Mode Tasks (Renamed from Cloud Mode)

Rename all instances of "cloud mode" to "forwarding mode" in codebase
Update cloud_processor.py to forwarding_processor.py
Modify CLI commands from tgarchive cloud to tgarchive forward
Update documentation to reflect forwarding mode terminology
Rename cloud configuration section to forwarding configuration

Scheduling Service Foundation

Create scheduler_service.py module
Implement SchedulerDaemon class for background execution
Add scheduler configuration to spectra_config.json
Create scheduler_state.json for persistent job tracking
Implement cron-style schedule parser
Add timezone support for scheduling
Create scheduler CLI commands (--schedule-add, --schedule-list, --schedule-remove)
Implement systemd service file for scheduler daemon
Add Windows service support for scheduler
Create scheduler health check endpoint

Channel Forwarding Scheduler

Create ChannelForwardSchedule database table
Implement scheduled_channel_forward() function
Add channel schedule configuration (channel_id, destination, interval)
Create channel forwarding job executor
Implement channel message checkpoint tracking
Add support for multiple channel schedules
Create channel schedule validation logic
Implement channel schedule conflict detection
Add channel forwarding statistics tracking
Create channel schedule notification system

File-Specific Forwarding Scheduler

Create FileForwardSchedule database table
Implement scheduled_file_forward() function
Add file type filter configuration for schedules
Create file-specific job executor
Implement file deduplication for scheduled forwards
Add file size limit configuration
Create file forwarding queue management
Implement file schedule priority system
Add file forwarding bandwidth throttling
Create file schedule reporting system

File Type Sorting System

Create FileTypeSorter class
Implement MIME type detection using python-magic
Add file extension mapping configuration
Create category definitions (text, pdf, archive, image, video, etc.)
Implement get_file_category() method
Add custom category support
Create category-to-group mapping table
Implement category priority system
Add unknown file type handling
Create category statistics tracking

Dynamic Group Management

Create GroupManager class for dynamic group creation
Implement create_category_group() method
Add group naming template system
Create group description templates
Implement check_or_create_group() logic
Add group creation rate limiting
Create group metadata caching
Implement group member management
Add group privacy settings configuration
Create group creation failure recovery

Sorting Groups Configuration

Create sorting_groups table in database
Implement default sorting group templates
Add text files group configuration
Add PDF files group configuration
Add archive files group configuration
Add image files group configuration
Add video files group configuration
Add document files group configuration
Add source code files group configuration
Create miscellaneous files group

Mass Migration Mode (Shunt Mode)

Create MassMigrationManager class
Implement one_time_migration() method
Add migration source configuration
Create migration progress tracking
Implement migration checkpoint system
Add migration rollback capability
Create migration dry-run mode
Implement migration speed optimization
Add migration error recovery
Create migration completion report

Forwarding with Sorting Integration

Create SortingForwarder class extending AttachmentForwarder
Implement sort_and_forward() method
Add file classification pipeline
Create group resolution logic
Implement sorted forwarding queue
Add sorting cache for performance
Create sorting statistics collector
Implement sorting error handling
Add sorting preview mode
Create sorting audit log

Attribution System

Create AttributionFormatter class
Implement attribution template system
Add source channel information extraction
Create timestamp formatting options
Implement message ID preservation
Add original sender attribution
Create attribution style configuration
Implement attribution caching
Add attribution disable option per group
Create attribution statistics

Configuration Management

Add forwarding_mode section to config
Create scheduling configuration schema
Add sorting_enabled boolean flag
Create group_creation_enabled flag
Implement migration_mode configuration
Add file_categories configuration list
Create attribution_format configuration
Implement schedule_check_interval setting
Add max_concurrent_forwards limit
Create error_retry_attempts configuration

Performance Optimization

Implement connection pooling for forwarding
Create batch forwarding optimization
Add parallel file classification
Implement forward queue prioritization
Create memory-efficient file streaming
Add API rate limit management
Implement adaptive scheduling
Create resource usage monitoring
Add performance metrics collection
Implement cache warming strategies

Error Handling & Recovery

Create comprehensive error classification
Implement exponential backoff for retries
Add dead letter queue for failed forwards
Create error notification system
Implement partial failure recovery
Add transaction-like forwarding
Create error diagnostics tools
Implement automatic error recovery
Add manual intervention interface
Create error reporting dashboard

Testing Tasks

Create unit tests for FileTypeSorter
Implement scheduler service tests
Add mass migration integration tests
Create sorting accuracy tests
Implement group creation tests
Add attribution format tests
Create performance benchmark tests
Implement error scenario tests
Add configuration validation tests
Create end-to-end workflow tests

Documentation Tasks

Write forwarding mode user guide
Create scheduling configuration examples
Document file type categories
Write mass migration guide
Create troubleshooting documentation
Document API changes
Write performance tuning guide
Create security best practices
Document backup procedures
Write disaster recovery guide

CLI Interface Tasks

Implement tgarchive forward --schedule command
Create tgarchive forward --sort command
Add tgarchive migrate --one-time command
Implement tgarchive schedule --list command
Create tgarchive groups --create-sorting command

Success Metrics:

Scheduling service runs continuously without memory leaks
File sorting accuracy exceeds 98%
Mass migration handles 10TB+ without data loss
Dynamic group creation completes in <3 seconds
Attribution maintains source integrity 100%
Scheduled forwards execute within 1 minute of scheduled time
