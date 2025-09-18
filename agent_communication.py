#!/usr/bin/env python3
"""
SPECTRA Agent Communication and Synchronization Protocols
==========================================================

Advanced communication protocols for multi-agent coordination with
message routing, synchronization mechanisms, and failure recovery.

Author: COORDINATOR Agent - Multi-Agent Orchestration Specialist
Date: September 18, 2025
"""

import asyncio
import logging
import json
import time
import threading
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Callable, Set, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
import weakref
from pathlib import Path

# SPECTRA imports
from spectra_orchestrator import AgentStatus, AgentMetadata


class MessageType(Enum):
    """Message types for agent communication"""
    TASK_REQUEST = "task_request"
    TASK_RESPONSE = "task_response"
    STATUS_UPDATE = "status_update"
    HEARTBEAT = "heartbeat"
    COORDINATION = "coordination"
    NOTIFICATION = "notification"
    SYNC_REQUEST = "sync_request"
    SYNC_RESPONSE = "sync_response"
    BARRIER_REQUEST = "barrier_request"
    BARRIER_RESPONSE = "barrier_response"
    HANDOFF = "handoff"
    ERROR = "error"


class MessagePriority(Enum):
    """Message priority levels"""
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    BACKGROUND = 5


class SynchronizationType(Enum):
    """Synchronization mechanism types"""
    BARRIER = "barrier"           # Wait for all agents to reach a point
    CONSENSUS = "consensus"       # Reach agreement on a decision
    ELECTION = "election"         # Elect a leader
    BROADCAST = "broadcast"       # Send to all agents
    MULTICAST = "multicast"       # Send to specific group
    UNICAST = "unicast"           # Send to specific agent


class DeliveryGuarantee(Enum):
    """Message delivery guarantees"""
    AT_MOST_ONCE = "at_most_once"       # May lose messages
    AT_LEAST_ONCE = "at_least_once"     # May duplicate messages
    EXACTLY_ONCE = "exactly_once"       # Exactly one delivery


@dataclass
class Message:
    """Agent communication message"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType = MessageType.TASK_REQUEST
    sender: str = ""
    receiver: str = ""
    content: Dict[str, Any] = field(default_factory=dict)
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    reply_to: Optional[str] = None
    correlation_id: Optional[str] = None
    attempt_count: int = 0
    max_attempts: int = 3
    delivery_guarantee: DeliveryGuarantee = DeliveryGuarantee.AT_LEAST_ONCE
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentEndpoint:
    """Agent communication endpoint"""
    agent_id: str
    address: str
    port: int
    protocol: str = "tcp"
    capabilities: List[str] = field(default_factory=list)
    last_seen: datetime = field(default_factory=datetime.now)
    heartbeat_interval: int = 30  # seconds
    is_alive: bool = True


@dataclass
class SynchronizationBarrier:
    """Synchronization barrier for coordinating multiple agents"""
    id: str
    participants: Set[str]
    arrived: Set[str] = field(default_factory=set)
    timeout: Optional[datetime] = None
    callback: Optional[Callable] = None
    result: Optional[Any] = None
    is_complete: bool = False


@dataclass
class ConsensusGroup:
    """Consensus group for distributed decision making"""
    id: str
    participants: Set[str]
    proposal: Optional[Dict[str, Any]] = None
    votes: Dict[str, bool] = field(default_factory=dict)
    required_votes: int = 0
    timeout: Optional[datetime] = None
    is_complete: bool = False
    result: Optional[bool] = None


class AgentCommunicationBus:
    """
    Advanced communication bus for SPECTRA agents with message routing,
    synchronization primitives, and failure recovery mechanisms.
    """

    def __init__(self,
                 max_message_queue_size: int = 10000,
                 default_timeout: int = 30,
                 heartbeat_interval: int = 30):
        """Initialize the communication bus"""
        self.max_queue_size = max_message_queue_size
        self.default_timeout = default_timeout
        self.heartbeat_interval = heartbeat_interval

        # Message routing and queuing
        self.message_queues: Dict[str, asyncio.Queue] = {}
        self.message_handlers: Dict[str, Dict[MessageType, Callable]] = {}
        self.pending_messages: Dict[str, Message] = {}
        self.message_history: List[Message] = []

        # Agent registry and endpoints
        self.agents: Dict[str, AgentEndpoint] = {}
        self.agent_groups: Dict[str, Set[str]] = {}

        # Synchronization mechanisms
        self.barriers: Dict[str, SynchronizationBarrier] = {}
        self.consensus_groups: Dict[str, ConsensusGroup] = {}
        self.elected_leaders: Dict[str, str] = {}

        # Communication state
        self.is_running = False
        self.message_counter = 0
        self.total_messages_sent = 0
        self.total_messages_received = 0
        self.failed_deliveries = 0

        # Threading and synchronization
        self.executor = ThreadPoolExecutor(max_workers=8)
        self.comm_lock = threading.RLock()
        self.sync_lock = threading.RLock()

        # Logging
        self.logger = logging.getLogger(__name__)

        # Weak references to avoid memory leaks
        self.subscribers: Dict[str, List[weakref.WeakMethod]] = {}

    async def start_communication_bus(self):
        """Start the communication bus"""
        if self.is_running:
            self.logger.warning("Communication bus is already running")
            return

        self.is_running = True
        self.logger.info("Starting SPECTRA Agent Communication Bus")

        try:
            # Start communication loops
            await asyncio.gather(
                self._message_routing_loop(),
                self._heartbeat_loop(),
                self._timeout_cleanup_loop(),
                self._synchronization_loop()
            )
        except Exception as e:
            self.logger.error(f"Communication bus error: {e}", exc_info=True)
        finally:
            self.is_running = False

    async def stop_communication_bus(self):
        """Stop the communication bus"""
        self.logger.info("Stopping SPECTRA Agent Communication Bus")
        self.is_running = False
        self.executor.shutdown(wait=True)

    async def register_agent(self,
                           agent_id: str,
                           address: str = "localhost",
                           port: int = 0,
                           capabilities: List[str] = None) -> bool:
        """Register an agent with the communication bus"""
        try:
            with self.comm_lock:
                endpoint = AgentEndpoint(
                    agent_id=agent_id,
                    address=address,
                    port=port,
                    capabilities=capabilities or [],
                    last_seen=datetime.now(),
                    is_alive=True
                )

                self.agents[agent_id] = endpoint
                self.message_queues[agent_id] = asyncio.Queue(maxsize=self.max_queue_size)
                self.message_handlers[agent_id] = {}

            self.logger.info(f"Registered agent: {agent_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to register agent {agent_id}: {e}")
            return False

    async def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent from the communication bus"""
        try:
            with self.comm_lock:
                if agent_id in self.agents:
                    del self.agents[agent_id]

                if agent_id in self.message_queues:
                    del self.message_queues[agent_id]

                if agent_id in self.message_handlers:
                    del self.message_handlers[agent_id]

                # Remove from groups
                for group_agents in self.agent_groups.values():
                    group_agents.discard(agent_id)

            self.logger.info(f"Unregistered agent: {agent_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to unregister agent {agent_id}: {e}")
            return False

    async def register_message_handler(self,
                                     agent_id: str,
                                     message_type: MessageType,
                                     handler: Callable[[Message], Any]) -> bool:
        """Register a message handler for an agent"""
        try:
            with self.comm_lock:
                if agent_id not in self.message_handlers:
                    self.message_handlers[agent_id] = {}

                self.message_handlers[agent_id][message_type] = handler

            self.logger.debug(f"Registered handler for {agent_id}: {message_type.value}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to register handler for {agent_id}: {e}")
            return False

    async def send_message(self, message: Message) -> bool:
        """Send a message to an agent"""
        try:
            message.id = str(uuid.uuid4())
            message.timestamp = datetime.now()
            message.attempt_count += 1

            with self.comm_lock:
                self.message_counter += 1
                self.total_messages_sent += 1

                # Check if receiver exists
                if message.receiver not in self.agents:
                    self.logger.warning(f"Unknown receiver: {message.receiver}")
                    return False

                # Add to message history
                self.message_history.append(message)
                if len(self.message_history) > 1000:  # Keep last 1000 messages
                    self.message_history.pop(0)

                # Queue message for delivery
                await self._queue_message(message)

            self.logger.debug(f"Sent message {message.id} from {message.sender} to {message.receiver}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send message: {e}")
            self.failed_deliveries += 1
            return False

    async def send_request(self,
                         sender: str,
                         receiver: str,
                         content: Dict[str, Any],
                         timeout: Optional[int] = None) -> Optional[Message]:
        """Send a request and wait for response"""
        try:
            request = Message(
                type=MessageType.TASK_REQUEST,
                sender=sender,
                receiver=receiver,
                content=content,
                correlation_id=str(uuid.uuid4()),
                expires_at=datetime.now() + timedelta(seconds=timeout or self.default_timeout)
            )

            # Send request
            if not await self.send_message(request):
                return None

            # Wait for response
            response = await self._wait_for_response(request.correlation_id, timeout or self.default_timeout)
            return response

        except Exception as e:
            self.logger.error(f"Request failed: {e}")
            return None

    async def send_response(self, original_message: Message, content: Dict[str, Any]) -> bool:
        """Send a response to a request"""
        try:
            response = Message(
                type=MessageType.TASK_RESPONSE,
                sender=original_message.receiver,
                receiver=original_message.sender,
                content=content,
                reply_to=original_message.id,
                correlation_id=original_message.correlation_id
            )

            return await self.send_message(response)

        except Exception as e:
            self.logger.error(f"Failed to send response: {e}")
            return False

    async def broadcast_message(self,
                              sender: str,
                              content: Dict[str, Any],
                              message_type: MessageType = MessageType.NOTIFICATION) -> int:
        """Broadcast a message to all registered agents"""
        sent_count = 0

        try:
            with self.comm_lock:
                agents = list(self.agents.keys())

            for agent_id in agents:
                if agent_id != sender:  # Don't send to self
                    message = Message(
                        type=message_type,
                        sender=sender,
                        receiver=agent_id,
                        content=content.copy()
                    )

                    if await self.send_message(message):
                        sent_count += 1

            self.logger.info(f"Broadcast message from {sender} to {sent_count} agents")
            return sent_count

        except Exception as e:
            self.logger.error(f"Broadcast failed: {e}")
            return sent_count

    async def multicast_message(self,
                              sender: str,
                              receivers: List[str],
                              content: Dict[str, Any],
                              message_type: MessageType = MessageType.NOTIFICATION) -> int:
        """Send a message to multiple specific agents"""
        sent_count = 0

        try:
            for receiver in receivers:
                if receiver != sender and receiver in self.agents:
                    message = Message(
                        type=message_type,
                        sender=sender,
                        receiver=receiver,
                        content=content.copy()
                    )

                    if await self.send_message(message):
                        sent_count += 1

            self.logger.info(f"Multicast message from {sender} to {sent_count}/{len(receivers)} agents")
            return sent_count

        except Exception as e:
            self.logger.error(f"Multicast failed: {e}")
            return sent_count

    async def create_agent_group(self, group_name: str, agent_ids: List[str]) -> bool:
        """Create a group of agents for coordinated operations"""
        try:
            with self.comm_lock:
                # Validate all agents exist
                for agent_id in agent_ids:
                    if agent_id not in self.agents:
                        self.logger.warning(f"Agent {agent_id} not found for group {group_name}")
                        return False

                self.agent_groups[group_name] = set(agent_ids)

            self.logger.info(f"Created agent group '{group_name}' with {len(agent_ids)} agents")
            return True

        except Exception as e:
            self.logger.error(f"Failed to create group {group_name}: {e}")
            return False

    async def create_synchronization_barrier(self,
                                           barrier_id: str,
                                           participants: List[str],
                                           timeout_seconds: Optional[int] = None) -> str:
        """Create a synchronization barrier for coordinating multiple agents"""
        try:
            with self.sync_lock:
                timeout = None
                if timeout_seconds:
                    timeout = datetime.now() + timedelta(seconds=timeout_seconds)

                barrier = SynchronizationBarrier(
                    id=barrier_id,
                    participants=set(participants),
                    timeout=timeout
                )

                self.barriers[barrier_id] = barrier

            self.logger.info(f"Created synchronization barrier '{barrier_id}' for {len(participants)} agents")
            return barrier_id

        except Exception as e:
            self.logger.error(f"Failed to create barrier {barrier_id}: {e}")
            raise

    async def wait_at_barrier(self, barrier_id: str, agent_id: str) -> bool:
        """Agent arrives at synchronization barrier and waits for others"""
        try:
            with self.sync_lock:
                if barrier_id not in self.barriers:
                    self.logger.error(f"Barrier {barrier_id} not found")
                    return False

                barrier = self.barriers[barrier_id]

                if agent_id not in barrier.participants:
                    self.logger.error(f"Agent {agent_id} not in barrier {barrier_id}")
                    return False

                if barrier.is_complete:
                    return True

                # Agent arrives at barrier
                barrier.arrived.add(agent_id)
                self.logger.debug(f"Agent {agent_id} arrived at barrier {barrier_id} "
                                f"({len(barrier.arrived)}/{len(barrier.participants)})")

                # Check if all agents have arrived
                if len(barrier.arrived) == len(barrier.participants):
                    barrier.is_complete = True
                    self.logger.info(f"Barrier {barrier_id} completed")

                    # Notify all waiting agents
                    await self._notify_barrier_completion(barrier)
                    return True

            # Wait for barrier completion
            while not self.barriers.get(barrier_id, SynchronizationBarrier("", set())).is_complete:
                await asyncio.sleep(0.1)

                # Check timeout
                barrier = self.barriers.get(barrier_id)
                if barrier and barrier.timeout and datetime.now() > barrier.timeout:
                    self.logger.warning(f"Barrier {barrier_id} timed out")
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Barrier wait failed for {agent_id} at {barrier_id}: {e}")
            return False

    async def start_consensus(self,
                            consensus_id: str,
                            participants: List[str],
                            proposal: Dict[str, Any],
                            required_votes: Optional[int] = None,
                            timeout_seconds: Optional[int] = None) -> str:
        """Start a consensus process among agents"""
        try:
            with self.sync_lock:
                timeout = None
                if timeout_seconds:
                    timeout = datetime.now() + timedelta(seconds=timeout_seconds)

                # Default to majority vote
                if required_votes is None:
                    required_votes = (len(participants) // 2) + 1

                consensus = ConsensusGroup(
                    id=consensus_id,
                    participants=set(participants),
                    proposal=proposal,
                    required_votes=required_votes,
                    timeout=timeout
                )

                self.consensus_groups[consensus_id] = consensus

            # Send proposal to all participants
            for participant in participants:
                message = Message(
                    type=MessageType.SYNC_REQUEST,
                    sender="COMMUNICATION_BUS",
                    receiver=participant,
                    content={
                        "consensus_id": consensus_id,
                        "proposal": proposal,
                        "action": "vote"
                    }
                )
                await self.send_message(message)

            self.logger.info(f"Started consensus '{consensus_id}' with {len(participants)} participants")
            return consensus_id

        except Exception as e:
            self.logger.error(f"Failed to start consensus {consensus_id}: {e}")
            raise

    async def vote_on_consensus(self, consensus_id: str, agent_id: str, vote: bool) -> Optional[bool]:
        """Agent votes on a consensus proposal"""
        try:
            with self.sync_lock:
                if consensus_id not in self.consensus_groups:
                    self.logger.error(f"Consensus {consensus_id} not found")
                    return None

                consensus = self.consensus_groups[consensus_id]

                if agent_id not in consensus.participants:
                    self.logger.error(f"Agent {agent_id} not in consensus {consensus_id}")
                    return None

                if consensus.is_complete:
                    return consensus.result

                # Record vote
                consensus.votes[agent_id] = vote
                self.logger.debug(f"Agent {agent_id} voted {vote} on consensus {consensus_id} "
                                f"({len(consensus.votes)}/{len(consensus.participants)})")

                # Check if consensus reached
                yes_votes = sum(1 for v in consensus.votes.values() if v)
                no_votes = len(consensus.votes) - yes_votes

                if yes_votes >= consensus.required_votes:
                    consensus.is_complete = True
                    consensus.result = True
                    self.logger.info(f"Consensus {consensus_id} passed ({yes_votes} yes votes)")

                elif no_votes > len(consensus.participants) - consensus.required_votes:
                    consensus.is_complete = True
                    consensus.result = False
                    self.logger.info(f"Consensus {consensus_id} failed ({no_votes} no votes)")

                # Notify all participants if complete
                if consensus.is_complete:
                    await self._notify_consensus_completion(consensus)

                return consensus.result

        except Exception as e:
            self.logger.error(f"Consensus vote failed for {agent_id} on {consensus_id}: {e}")
            return None

    async def elect_leader(self,
                         election_id: str,
                         candidates: List[str],
                         voters: List[str]) -> Optional[str]:
        """Conduct leader election among agents"""
        try:
            # Start consensus for leader election
            proposal = {
                "type": "leader_election",
                "candidates": candidates,
                "election_id": election_id
            }

            consensus_id = f"election_{election_id}"
            await self.start_consensus(consensus_id, voters, proposal, len(voters))

            # Wait for election completion
            while consensus_id in self.consensus_groups:
                consensus = self.consensus_groups[consensus_id]
                if consensus.is_complete:
                    if consensus.result:
                        # Simple election: first candidate wins (would implement better algorithm)
                        leader = candidates[0] if candidates else None
                        if leader:
                            self.elected_leaders[election_id] = leader
                            self.logger.info(f"Elected leader for {election_id}: {leader}")
                        return leader
                    else:
                        self.logger.info(f"Leader election {election_id} failed")
                        return None

                await asyncio.sleep(0.1)

            return None

        except Exception as e:
            self.logger.error(f"Leader election failed for {election_id}: {e}")
            return None

    async def get_communication_stats(self) -> Dict[str, Any]:
        """Get communication bus statistics"""
        with self.comm_lock:
            return {
                "is_running": self.is_running,
                "registered_agents": len(self.agents),
                "active_queues": len(self.message_queues),
                "total_messages_sent": self.total_messages_sent,
                "total_messages_received": self.total_messages_received,
                "failed_deliveries": self.failed_deliveries,
                "message_history_size": len(self.message_history),
                "active_barriers": len(self.barriers),
                "active_consensus": len(self.consensus_groups),
                "agent_groups": len(self.agent_groups),
                "elected_leaders": len(self.elected_leaders),
                "agents": {
                    agent_id: {
                        "address": endpoint.address,
                        "port": endpoint.port,
                        "is_alive": endpoint.is_alive,
                        "last_seen": endpoint.last_seen.isoformat(),
                        "capabilities": endpoint.capabilities
                    }
                    for agent_id, endpoint in self.agents.items()
                }
            }

    async def _queue_message(self, message: Message):
        """Queue message for delivery to agent"""
        if message.receiver in self.message_queues:
            queue = self.message_queues[message.receiver]
            try:
                await queue.put(message)
            except asyncio.QueueFull:
                self.logger.warning(f"Message queue full for agent {message.receiver}")
                raise

    async def _wait_for_response(self, correlation_id: str, timeout: int) -> Optional[Message]:
        """Wait for a response message with specific correlation ID"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Check message history for response
            for message in reversed(self.message_history):
                if (message.correlation_id == correlation_id and
                    message.type == MessageType.TASK_RESPONSE):
                    return message

            await asyncio.sleep(0.1)

        return None

    async def _message_routing_loop(self):
        """Main message routing and delivery loop"""
        while self.is_running:
            try:
                # Process queued messages for all agents
                for agent_id, queue in self.message_queues.items():
                    try:
                        if not queue.empty():
                            message = await asyncio.wait_for(queue.get(), timeout=0.1)
                            await self._deliver_message(agent_id, message)
                            self.total_messages_received += 1
                    except asyncio.TimeoutError:
                        continue

                await asyncio.sleep(0.01)  # Small delay to prevent busy waiting

            except Exception as e:
                self.logger.error(f"Message routing loop error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _deliver_message(self, agent_id: str, message: Message):
        """Deliver message to specific agent"""
        try:
            # Check if agent has handler for this message type
            if (agent_id in self.message_handlers and
                message.type in self.message_handlers[agent_id]):

                handler = self.message_handlers[agent_id][message.type]

                # Execute handler in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(self.executor, handler, message)

            else:
                self.logger.debug(f"No handler for {message.type.value} in agent {agent_id}")

        except Exception as e:
            self.logger.error(f"Message delivery failed for {agent_id}: {e}")

    async def _heartbeat_loop(self):
        """Heartbeat loop to monitor agent health"""
        while self.is_running:
            try:
                current_time = datetime.now()

                with self.comm_lock:
                    for agent_id, endpoint in self.agents.items():
                        # Check if agent has timed out
                        time_since_last_seen = current_time - endpoint.last_seen
                        if time_since_last_seen.total_seconds() > endpoint.heartbeat_interval * 3:
                            if endpoint.is_alive:
                                endpoint.is_alive = False
                                self.logger.warning(f"Agent {agent_id} appears to be down")

                        # Send heartbeat request
                        heartbeat_message = Message(
                            type=MessageType.HEARTBEAT,
                            sender="COMMUNICATION_BUS",
                            receiver=agent_id,
                            content={"timestamp": current_time.isoformat()}
                        )
                        await self.send_message(heartbeat_message)

                await asyncio.sleep(self.heartbeat_interval)

            except Exception as e:
                self.logger.error(f"Heartbeat loop error: {e}", exc_info=True)
                await asyncio.sleep(30)

    async def _timeout_cleanup_loop(self):
        """Cleanup loop for expired messages and synchronization objects"""
        while self.is_running:
            try:
                current_time = datetime.now()

                # Clean up expired barriers
                with self.sync_lock:
                    expired_barriers = []
                    for barrier_id, barrier in self.barriers.items():
                        if barrier.timeout and current_time > barrier.timeout:
                            expired_barriers.append(barrier_id)

                    for barrier_id in expired_barriers:
                        self.logger.warning(f"Barrier {barrier_id} expired")
                        del self.barriers[barrier_id]

                    # Clean up expired consensus groups
                    expired_consensus = []
                    for consensus_id, consensus in self.consensus_groups.items():
                        if consensus.timeout and current_time > consensus.timeout:
                            expired_consensus.append(consensus_id)

                    for consensus_id in expired_consensus:
                        self.logger.warning(f"Consensus {consensus_id} expired")
                        del self.consensus_groups[consensus_id]

                # Clean up old messages
                cutoff_time = current_time - timedelta(hours=1)
                self.message_history = [
                    msg for msg in self.message_history
                    if msg.timestamp > cutoff_time
                ]

                await asyncio.sleep(60)  # Clean up every minute

            except Exception as e:
                self.logger.error(f"Cleanup loop error: {e}", exc_info=True)
                await asyncio.sleep(120)

    async def _synchronization_loop(self):
        """Loop to handle synchronization operations"""
        while self.is_running:
            try:
                # Check barrier completions
                with self.sync_lock:
                    for barrier in self.barriers.values():
                        if (not barrier.is_complete and
                            len(barrier.arrived) == len(barrier.participants)):
                            barrier.is_complete = True
                            await self._notify_barrier_completion(barrier)

                await asyncio.sleep(1)

            except Exception as e:
                self.logger.error(f"Synchronization loop error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _notify_barrier_completion(self, barrier: SynchronizationBarrier):
        """Notify all participants that barrier is complete"""
        try:
            for participant in barrier.participants:
                message = Message(
                    type=MessageType.SYNC_RESPONSE,
                    sender="COMMUNICATION_BUS",
                    receiver=participant,
                    content={
                        "barrier_id": barrier.id,
                        "status": "complete",
                        "result": barrier.result
                    }
                )
                await self.send_message(message)

        except Exception as e:
            self.logger.error(f"Failed to notify barrier completion: {e}")

    async def _notify_consensus_completion(self, consensus: ConsensusGroup):
        """Notify all participants that consensus is complete"""
        try:
            for participant in consensus.participants:
                message = Message(
                    type=MessageType.SYNC_RESPONSE,
                    sender="COMMUNICATION_BUS",
                    receiver=participant,
                    content={
                        "consensus_id": consensus.id,
                        "status": "complete",
                        "result": consensus.result,
                        "votes": dict(consensus.votes)
                    }
                )
                await self.send_message(message)

        except Exception as e:
            self.logger.error(f"Failed to notify consensus completion: {e}")


# Example usage and integration
class SpectraAgentProxy:
    """Proxy class for integrating agents with the communication bus"""

    def __init__(self, agent_id: str, communication_bus: AgentCommunicationBus):
        self.agent_id = agent_id
        self.comm_bus = communication_bus
        self.logger = logging.getLogger(f"{__name__}.{agent_id}")

    async def initialize(self, capabilities: List[str] = None):
        """Initialize agent with communication bus"""
        await self.comm_bus.register_agent(self.agent_id, capabilities=capabilities or [])

        # Register default handlers
        await self.comm_bus.register_message_handler(
            self.agent_id, MessageType.HEARTBEAT, self._handle_heartbeat
        )
        await self.comm_bus.register_message_handler(
            self.agent_id, MessageType.TASK_REQUEST, self._handle_task_request
        )

    async def send_to_agent(self, target_agent: str, content: Dict[str, Any]) -> bool:
        """Send message to another agent"""
        message = Message(
            type=MessageType.TASK_REQUEST,
            sender=self.agent_id,
            receiver=target_agent,
            content=content
        )
        return await self.comm_bus.send_message(message)

    async def request_from_agent(self, target_agent: str, content: Dict[str, Any], timeout: int = 30) -> Optional[Message]:
        """Send request to agent and wait for response"""
        return await self.comm_bus.send_request(self.agent_id, target_agent, content, timeout)

    async def broadcast_status(self, status: AgentStatus, details: Dict[str, Any] = None):
        """Broadcast status update to all agents"""
        content = {
            "status": status.value,
            "timestamp": datetime.now().isoformat(),
            "details": details or {}
        }
        await self.comm_bus.broadcast_message(self.agent_id, content, MessageType.STATUS_UPDATE)

    async def join_barrier(self, barrier_id: str) -> bool:
        """Join a synchronization barrier"""
        return await self.comm_bus.wait_at_barrier(barrier_id, self.agent_id)

    async def vote_consensus(self, consensus_id: str, vote: bool) -> Optional[bool]:
        """Vote on a consensus proposal"""
        return await self.comm_bus.vote_on_consensus(consensus_id, self.agent_id, vote)

    def _handle_heartbeat(self, message: Message):
        """Handle heartbeat message"""
        # Update last seen timestamp
        if self.agent_id in self.comm_bus.agents:
            self.comm_bus.agents[self.agent_id].last_seen = datetime.now()

    def _handle_task_request(self, message: Message):
        """Handle task request message"""
        # Default implementation - would be overridden by specific agents
        self.logger.info(f"Received task request: {message.content}")


# Example usage and testing
async def main():
    """Example usage of the communication system"""

    # Initialize communication bus
    comm_bus = AgentCommunicationBus()

    # Start communication bus
    bus_task = asyncio.create_task(comm_bus.start_communication_bus())

    # Create agent proxies
    director_proxy = SpectraAgentProxy("DIRECTOR", comm_bus)
    database_proxy = SpectraAgentProxy("DATABASE", comm_bus)
    optimizer_proxy = SpectraAgentProxy("OPTIMIZER", comm_bus)

    # Initialize agents
    await director_proxy.initialize(["strategic_planning", "coordination"])
    await database_proxy.initialize(["data_management", "migration"])
    await optimizer_proxy.initialize(["performance_tuning", "optimization"])

    # Test basic communication
    await director_proxy.send_to_agent("DATABASE", {"action": "setup_cluster"})

    # Test request-response
    response = await director_proxy.request_from_agent(
        "OPTIMIZER",
        {"action": "analyze_performance"},
        timeout=10
    )
    print(f"Response: {response}")

    # Test synchronization barrier
    barrier_id = await comm_bus.create_synchronization_barrier(
        "phase1_completion",
        ["DIRECTOR", "DATABASE", "OPTIMIZER"],
        timeout_seconds=60
    )

    # Simulate barrier usage
    await director_proxy.join_barrier(barrier_id)
    print("Director reached barrier")

    # Test consensus
    consensus_id = await comm_bus.start_consensus(
        "deployment_decision",
        ["DIRECTOR", "DATABASE", "OPTIMIZER"],
        {"deploy_to_production": True},
        required_votes=2,
        timeout_seconds=30
    )

    # Vote on consensus
    result = await director_proxy.vote_consensus(consensus_id, True)
    print(f"Consensus result: {result}")

    # Get statistics
    stats = await comm_bus.get_communication_stats()
    print(f"Communication stats: {json.dumps(stats, indent=2, default=str)}")

    # Cleanup
    await comm_bus.stop_communication_bus()


if __name__ == "__main__":
    asyncio.run(main())