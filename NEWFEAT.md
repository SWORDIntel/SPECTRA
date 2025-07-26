[x] JULES TASK LIST: SPECTRA Forwarding & Scheduling System
[x] Core Forwarding Mode Tasks (Renamed from Cloud Mode)

[x] Rename all instances of "forwarding mode" to "forwarding mode" in codebase
[x] Update cloud_processor.py to forwarding_processor.py
[x] Modify CLI commands from tgarchive cloud to tgarchive forward
[x] Update documentation to reflect forwarding mode terminology
[x] Rename cloud configuration section to forwarding configuration

[x] Scheduling Service Foundation

[x] Create scheduler_service.py module
[x] Implement SchedulerDaemon class for background execution
[x] Add scheduler configuration to spectra_config.json
[x] Create scheduler_state.json for persistent job tracking
[x] Implement cron-style schedule parser
[x] Add timezone support for scheduling
[x] Create scheduler CLI commands (--schedule-add, --schedule-list, --schedule-remove)
[x] Implement systemd service file for scheduler daemon
[x] Add Windows service support for scheduler
[x] Create scheduler health check endpoint

[x] Channel Forwarding Scheduler

[x] Create ChannelForwardSchedule database table
[x] Implement scheduled_channel_forward() function
[x] Add channel schedule configuration (channel_id, destination, interval)
[x] Create channel forwarding job executor
[x] Implement channel message checkpoint tracking
[x] Add support for multiple channel schedules
[x] Create channel schedule validation logic
[x] Implement channel schedule conflict detection
[x] Add channel forwarding statistics tracking
[x] Create channel schedule notification system

[x] File-Specific Forwarding Scheduler

[x] Create FileForwardSchedule database table
[x] Implement scheduled_file_forward() function
[x] Add file type filter configuration for schedules
[x] Create file-specific job executor
[x] Implement file deduplication for scheduled forwards
[x] Add file size limit configuration
[x] Create file forwarding queue management
[x] Implement file schedule priority system
[x] Add file forwarding bandwidth throttling
[x] Create file schedule reporting system

[x] File Type Sorting System

[x] Create FileTypeSorter class
[x] Implement MIME type detection using python-magic
[x] Add file extension mapping configuration
[x] Create category definitions (text, pdf, archive, image, video, etc.)
[x] Implement get_file_category() method
[x] Add custom category support
[x] Create category-to-group mapping table
[x] Implement category priority system
[x] Add unknown file type handling
[x] Create category statistics tracking

[x] Dynamic Group Management

[x] Create GroupManager class for dynamic group creation
[x] Implement create_category_group() method
[x] Add group naming template system
[x] Create group description templates
[x] Implement check_or_create_group() logic
[x] Add group creation rate limiting
[x] Create group metadata caching
[x] Implement group member management
[x] Add group privacy settings configuration
[x] Create group creation failure recovery

[x] Sorting Groups Configuration

[x] Create sorting_groups table in database
[x] Implement default sorting group templates
[x] Add text files group configuration
[x] Add PDF files group configuration
[x] Add archive files group configuration
[x] Add image files group configuration
[x] Add video files group configuration
[x] Add document files group configuration
[x] Add source code files group configuration
[x] Create miscellaneous files group

[x] Mass Migration Mode (Shunt Mode)

[x] Create MassMigrationManager class
[x] Implement one_time_migration() method
[x] Add migration source configuration
[x] Create migration progress tracking
[x] Implement migration checkpoint system
[x] Add migration rollback capability
[x] Create migration dry-run mode
[x] Implement migration speed optimization
[x] Add migration error recovery
[x] Create migration completion report

[x] Forwarding with Sorting Integration

[x] Create SortingForwarder class extending AttachmentForwarder
[x] Implement sort_and_forward() method
[x] Add file classification pipeline
[x] Create group resolution logic
[x] Implement sorted forwarding queue
[x] Add sorting cache for performance
[x] Create sorting statistics collector
[x] Implement sorting error handling
[x] Add sorting preview mode
[x] Create sorting audit log

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
