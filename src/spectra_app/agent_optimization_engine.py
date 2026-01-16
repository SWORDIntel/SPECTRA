#!/usr/bin/env python3
"""
SPECTRA Agent Team Optimization Engine
=====================================

Advanced optimization algorithms for agent team composition, capability matching,
resource allocation, and performance prediction for multi-phase implementations.

Features:
- Multi-criteria optimization (performance, cost, reliability, speed, quality)
- Capability matrix analysis with compatibility scoring
- Resource allocation optimization with constraint satisfaction
- Success probability prediction using historical data
- Dynamic team rebalancing based on real-time performance
- Risk assessment and mitigation strategies

Author: PYTHON-INTERNAL Agent - Elite Python execution environment specialist
Date: September 18, 2025
"""

import asyncio
import logging
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict
import json
import math

# Optimization and ML libraries
try:
    from scipy.optimize import minimize, linear_sum_assignment
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.preprocessing import StandardScaler
    import networkx as nx
    OPTIMIZATION_LIBS_AVAILABLE = True
except ImportError:
    OPTIMIZATION_LIBS_AVAILABLE = False

# SPECTRA imports
from .spectra_orchestrator import AgentMetadata, Priority
from .orchestration_workflows import CoordinationPattern, SynchronizationMode


class OptimizationObjective(Enum):
    """Optimization objectives for team composition"""
    MINIMIZE_COST = "minimize_cost"
    MAXIMIZE_PERFORMANCE = "maximize_performance"
    MAXIMIZE_RELIABILITY = "maximize_reliability"
    MINIMIZE_TIME = "minimize_time"
    MAXIMIZE_QUALITY = "maximize_quality"
    BALANCED_APPROACH = "balanced_approach"


class ConstraintType(Enum):
    """Types of optimization constraints"""
    BUDGET_LIMIT = "budget_limit"
    TIME_LIMIT = "time_limit"
    RESOURCE_LIMIT = "resource_limit"
    CAPABILITY_REQUIREMENT = "capability_requirement"
    DEPENDENCY_CONSTRAINT = "dependency_constraint"
    WORKLOAD_BALANCE = "workload_balance"


@dataclass
class OptimizationConstraint:
    """Optimization constraint definition"""
    constraint_type: ConstraintType
    target_value: Any
    weight: float = 1.0
    is_hard_constraint: bool = True
    tolerance: float = 0.0


@dataclass
class CapabilityRequirement:
    """Capability requirement specification"""
    capability_name: str
    required_level: float  # 0.0 to 1.0
    weight: float = 1.0
    is_critical: bool = False
    alternatives: List[str] = field(default_factory=list)


@dataclass
class AgentPerformanceProfile:
    """Comprehensive agent performance profile"""
    agent_name: str
    capabilities: Dict[str, float]  # capability -> proficiency level
    performance_metrics: Dict[str, float]
    resource_efficiency: Dict[str, float]
    collaboration_scores: Dict[str, float]  # agent -> compatibility score
    workload_capacity: float
    cost_per_hour: float
    availability_probability: float
    learning_rate: float  # How quickly agent improves
    stress_tolerance: float  # Performance under high load
    specialization_breadth: float  # Generalist vs specialist


@dataclass
class TeamOptimizationResult:
    """Result of team optimization process"""
    team_composition: Dict[str, List[str]]  # role -> list of agents
    total_score: float
    objective_scores: Dict[OptimizationObjective, float]
    constraint_satisfaction: Dict[str, float]
    predicted_performance: Dict[str, float]
    risk_assessment: Dict[str, float]
    recommendations: List[str]
    alternative_compositions: List[Dict[str, Any]]


@dataclass
class WorkloadDistribution:
    """Workload distribution analysis"""
    agent_workloads: Dict[str, float]
    load_balance_score: float
    bottleneck_agents: List[str]
    underutilized_agents: List[str]
    redistribution_suggestions: List[Dict[str, Any]]


class AgentOptimizationEngine:
    """
    Advanced agent team optimization engine using multi-criteria optimization,
    constraint satisfaction, and machine learning for performance prediction.
    """

    def __init__(self, agents: Dict[str, AgentMetadata], historical_data: Optional[Dict] = None):
        """Initialize the optimization engine"""
        self.agents = agents
        self.historical_data = historical_data or {}

        # Performance profiles
        self.agent_profiles = {}
        self.capability_matrix = None
        self.compatibility_graph = None

        # Optimization models
        self.performance_predictor = None
        self.cost_estimator = None
        self.risk_assessor = None

        # Configuration
        self.optimization_weights = {
            OptimizationObjective.MAXIMIZE_PERFORMANCE: 0.3,
            OptimizationObjective.MINIMIZE_COST: 0.2,
            OptimizationObjective.MAXIMIZE_RELIABILITY: 0.2,
            OptimizationObjective.MINIMIZE_TIME: 0.15,
            OptimizationObjective.MAXIMIZE_QUALITY: 0.15
        }

        # Logging
        self.logger = logging.getLogger(__name__)

        # Initialize profiles and models
        self._initialize_agent_profiles()
        self._build_capability_matrix()
        self._build_compatibility_graph()
        if OPTIMIZATION_LIBS_AVAILABLE:
            self._train_prediction_models()

    def _initialize_agent_profiles(self):
        """Initialize comprehensive agent performance profiles"""
        for agent_name, agent in self.agents.items():
            # Extract capability proficiency from historical data
            capabilities = {}
            for cap in agent.capabilities:
                # Base proficiency from agent success rate
                base_proficiency = agent.success_rate

                # Adjust based on historical performance for this capability
                historical_perf = self.historical_data.get(agent_name, {}).get('capabilities', {}).get(cap, base_proficiency)
                capabilities[cap] = min(1.0, max(0.0, historical_perf))

            # Calculate performance metrics
            performance_metrics = {
                'throughput': 1.0 / max(0.1, agent.average_execution_time) if agent.average_execution_time > 0 else 1.0,
                'reliability': agent.success_rate,
                'efficiency': self._calculate_efficiency_score(agent_name),
                'adaptability': self._calculate_adaptability_score(agent_name)
            }

            # Resource efficiency (placeholder - would be calculated from actual resource usage)
            resource_efficiency = {
                'cpu_efficiency': 0.8,  # Would be calculated from actual usage
                'memory_efficiency': 0.7,
                'network_efficiency': 0.9,
                'storage_efficiency': 0.8
            }

            # Create comprehensive profile
            self.agent_profiles[agent_name] = AgentPerformanceProfile(
                agent_name=agent_name,
                capabilities=capabilities,
                performance_metrics=performance_metrics,
                resource_efficiency=resource_efficiency,
                collaboration_scores={},  # Will be calculated in compatibility graph
                workload_capacity=agent.max_concurrent_tasks,
                cost_per_hour=self._estimate_agent_cost(agent_name),
                availability_probability=self._calculate_availability_probability(agent_name),
                learning_rate=self._estimate_learning_rate(agent_name),
                stress_tolerance=self._estimate_stress_tolerance(agent_name),
                specialization_breadth=self._calculate_specialization_breadth(agent_name)
            )

    def _build_capability_matrix(self):
        """Build comprehensive capability matrix for all agents"""
        if not self.agent_profiles:
            return

        # Get all unique capabilities
        all_capabilities = set()
        for profile in self.agent_profiles.values():
            all_capabilities.update(profile.capabilities.keys())

        all_capabilities = sorted(list(all_capabilities))
        agent_names = sorted(list(self.agent_profiles.keys()))

        # Build matrix
        matrix = np.zeros((len(agent_names), len(all_capabilities)))

        for i, agent_name in enumerate(agent_names):
            profile = self.agent_profiles[agent_name]
            for j, capability in enumerate(all_capabilities):
                matrix[i, j] = profile.capabilities.get(capability, 0.0)

        self.capability_matrix = {
            'matrix': matrix,
            'agents': agent_names,
            'capabilities': all_capabilities
        }

    def _build_compatibility_graph(self):
        """Build agent compatibility graph using network analysis"""
        if not OPTIMIZATION_LIBS_AVAILABLE:
            self.logger.warning("NetworkX not available, using simplified compatibility calculation")
            self._build_simple_compatibility()
            return

        G = nx.Graph()

        # Add nodes (agents)
        for agent_name in self.agent_profiles.keys():
            G.add_node(agent_name)

        # Calculate compatibility scores and add edges
        agent_names = list(self.agent_profiles.keys())
        for i, agent1 in enumerate(agent_names):
            for j, agent2 in enumerate(agent_names[i+1:], i+1):
                compatibility = self._calculate_agent_compatibility(agent1, agent2)
                if compatibility > 0.3:  # Only add edges for significant compatibility
                    G.add_edge(agent1, agent2, weight=compatibility)

                # Update collaboration scores in profiles
                self.agent_profiles[agent1].collaboration_scores[agent2] = compatibility
                self.agent_profiles[agent2].collaboration_scores[agent1] = compatibility

        self.compatibility_graph = G

    def _build_simple_compatibility(self):
        """Build simplified compatibility scores without NetworkX"""
        agent_names = list(self.agent_profiles.keys())
        for i, agent1 in enumerate(agent_names):
            for j, agent2 in enumerate(agent_names[i+1:], i+1):
                compatibility = self._calculate_agent_compatibility(agent1, agent2)
                self.agent_profiles[agent1].collaboration_scores[agent2] = compatibility
                self.agent_profiles[agent2].collaboration_scores[agent1] = compatibility

    def _calculate_agent_compatibility(self, agent1: str, agent2: str) -> float:
        """Calculate compatibility score between two agents"""
        profile1 = self.agent_profiles[agent1]
        profile2 = self.agent_profiles[agent2]

        # Capability complementarity
        cap_similarity = 0.0
        cap_complementarity = 0.0
        all_caps = set(profile1.capabilities.keys()) | set(profile2.capabilities.keys())

        for cap in all_caps:
            val1 = profile1.capabilities.get(cap, 0.0)
            val2 = profile2.capabilities.get(cap, 0.0)

            # Similarity component
            cap_similarity += 1.0 - abs(val1 - val2)

            # Complementarity component (one strong where other is weak)
            if val1 > 0.7 and val2 < 0.4:
                cap_complementarity += 0.5
            elif val2 > 0.7 and val1 < 0.4:
                cap_complementarity += 0.5

        cap_similarity /= max(1, len(all_caps))
        cap_complementarity /= max(1, len(all_caps))

        # Performance synergy
        perf_synergy = (
            profile1.performance_metrics['reliability'] * profile2.performance_metrics['reliability'] +
            profile1.performance_metrics['efficiency'] * profile2.performance_metrics['efficiency']
        ) / 2.0

        # Resource compatibility
        resource_compat = 1.0  # Simplified - would check for resource conflicts

        # Calculate overall compatibility
        compatibility = (
            0.3 * cap_similarity +
            0.3 * cap_complementarity +
            0.2 * perf_synergy +
            0.2 * resource_compat
        )

        return min(1.0, max(0.0, compatibility))

    def optimize_team_composition(self,
                                 requirements: List[CapabilityRequirement],
                                 constraints: List[OptimizationConstraint],
                                 objective: OptimizationObjective = OptimizationObjective.BALANCED_APPROACH,
                                 team_size_range: Tuple[int, int] = (3, 8)) -> TeamOptimizationResult:
        """
        Optimize team composition based on requirements, constraints, and objectives.

        Uses multi-criteria optimization with constraint satisfaction.
        """

        # Phase 1: Filter available agents
        available_agents = self._filter_available_agents(constraints)

        if len(available_agents) < team_size_range[0]:
            raise ValueError(f"Not enough available agents ({len(available_agents)}) for minimum team size ({team_size_range[0]})")

        # Phase 2: Generate candidate teams
        candidate_teams = self._generate_candidate_teams(
            available_agents, requirements, team_size_range
        )

        # Phase 3: Evaluate and rank teams
        evaluated_teams = []
        for team in candidate_teams:
            evaluation = self._evaluate_team_composition(team, requirements, constraints, objective)
            evaluated_teams.append((team, evaluation))

        # Sort by total score
        evaluated_teams.sort(key=lambda x: x[1]['total_score'], reverse=True)

        # Phase 4: Build result
        if evaluated_teams:
            best_team, best_evaluation = evaluated_teams[0]

            # Get alternative compositions
            alternatives = []
            for team, evaluation in evaluated_teams[1:min(4, len(evaluated_teams))]:
                alternatives.append({
                    'team_composition': team,
                    'total_score': evaluation['total_score'],
                    'objective_scores': evaluation['objective_scores']
                })

            result = TeamOptimizationResult(
                team_composition=best_team,
                total_score=best_evaluation['total_score'],
                objective_scores=best_evaluation['objective_scores'],
                constraint_satisfaction=best_evaluation['constraint_satisfaction'],
                predicted_performance=best_evaluation['predicted_performance'],
                risk_assessment=best_evaluation['risk_assessment'],
                recommendations=self._generate_recommendations(best_team, best_evaluation),
                alternative_compositions=alternatives
            )

            return result
        else:
            raise ValueError("No valid team compositions found")

    def _generate_candidate_teams(self,
                                available_agents: List[str],
                                requirements: List[CapabilityRequirement],
                                team_size_range: Tuple[int, int]) -> List[Dict[str, List[str]]]:
        """Generate candidate team compositions using various strategies"""

        candidate_teams = []

        # Strategy 1: Capability-driven selection
        for team_size in range(team_size_range[0], min(team_size_range[1] + 1, len(available_agents) + 1)):
            teams = self._generate_capability_driven_teams(available_agents, requirements, team_size)
            candidate_teams.extend(teams)

        # Strategy 2: Performance-driven selection
        performance_teams = self._generate_performance_driven_teams(available_agents, team_size_range)
        candidate_teams.extend(performance_teams)

        # Strategy 3: Balanced selection
        balanced_teams = self._generate_balanced_teams(available_agents, requirements, team_size_range)
        candidate_teams.extend(balanced_teams)

        # Remove duplicates
        unique_teams = []
        seen_teams = set()
        for team in candidate_teams:
            team_signature = tuple(sorted(sum(team.values(), [])))
            if team_signature not in seen_teams:
                seen_teams.add(team_signature)
                unique_teams.append(team)

        return unique_teams[:50]  # Limit to top 50 candidates for performance

    def _generate_capability_driven_teams(self,
                                        available_agents: List[str],
                                        requirements: List[CapabilityRequirement],
                                        team_size: int) -> List[Dict[str, List[str]]]:
        """Generate teams focused on meeting capability requirements"""

        teams = []

        # Score agents for each required capability
        capability_agents = defaultdict(list)
        for req in requirements:
            agent_scores = []
            for agent in available_agents:
                profile = self.agent_profiles[agent]
                score = profile.capabilities.get(req.capability_name, 0.0)
                agent_scores.append((agent, score))

            # Sort by capability score
            agent_scores.sort(key=lambda x: x[1], reverse=True)
            capability_agents[req.capability_name] = agent_scores

        # Build teams ensuring capability coverage
        for _ in range(5):  # Generate 5 variations
            team = {'lead': [], 'specialists': [], 'support': []}
            selected_agents = set()

            # Select lead from top performers in critical capabilities
            critical_reqs = [req for req in requirements if req.is_critical]
            if critical_reqs:
                lead_candidates = capability_agents[critical_reqs[0].capability_name]
                for agent, score in lead_candidates:
                    if agent not in selected_agents and score > 0.7:
                        team['lead'].append(agent)
                        selected_agents.add(agent)
                        break

            # Select specialists for each capability requirement
            remaining_slots = team_size - len(selected_agents)
            for req in requirements:
                if remaining_slots <= 0:
                    break

                for agent, score in capability_agents[req.capability_name]:
                    if agent not in selected_agents and score > req.required_level:
                        team['specialists'].append(agent)
                        selected_agents.add(agent)
                        remaining_slots -= 1
                        break

            # Fill remaining slots with high-performing agents
            all_agents_by_perf = [(agent, self.agent_profiles[agent].performance_metrics['reliability'])
                                 for agent in available_agents if agent not in selected_agents]
            all_agents_by_perf.sort(key=lambda x: x[1], reverse=True)

            for agent, _ in all_agents_by_perf:
                if remaining_slots <= 0:
                    break
                team['support'].append(agent)
                selected_agents.add(agent)
                remaining_slots -= 1

            if len(selected_agents) >= team_size - 1:  # Allow some flexibility
                teams.append(team)

        return teams

    def _evaluate_team_composition(self,
                                 team: Dict[str, List[str]],
                                 requirements: List[CapabilityRequirement],
                                 constraints: List[OptimizationConstraint],
                                 objective: OptimizationObjective) -> Dict[str, Any]:
        """Comprehensively evaluate a team composition"""

        all_team_members = sum(team.values(), [])

        # Evaluate objective scores
        objective_scores = {}

        # Performance score
        performance_score = self._calculate_team_performance_score(all_team_members, requirements)
        objective_scores[OptimizationObjective.MAXIMIZE_PERFORMANCE] = performance_score

        # Cost score
        cost_score = self._calculate_team_cost_score(all_team_members)
        objective_scores[OptimizationObjective.MINIMIZE_COST] = cost_score

        # Reliability score
        reliability_score = self._calculate_team_reliability_score(all_team_members)
        objective_scores[OptimizationObjective.MAXIMIZE_RELIABILITY] = reliability_score

        # Time score
        time_score = self._calculate_team_time_score(all_team_members)
        objective_scores[OptimizationObjective.MINIMIZE_TIME] = time_score

        # Quality score
        quality_score = self._calculate_team_quality_score(all_team_members, requirements)
        objective_scores[OptimizationObjective.MAXIMIZE_QUALITY] = quality_score

        # Calculate total score based on objective
        if objective == OptimizationObjective.BALANCED_APPROACH:
            total_score = sum(score * self.optimization_weights[obj]
                            for obj, score in objective_scores.items())
        else:
            total_score = objective_scores[objective]

        # Evaluate constraint satisfaction
        constraint_satisfaction = {}
        for constraint in constraints:
            satisfaction = self._evaluate_constraint_satisfaction(all_team_members, constraint)
            constraint_satisfaction[constraint.constraint_type.value] = satisfaction

        # Predicted performance
        predicted_performance = self._predict_team_performance(all_team_members, requirements)

        # Risk assessment
        risk_assessment = self._assess_team_risks(all_team_members)

        return {
            'total_score': total_score,
            'objective_scores': objective_scores,
            'constraint_satisfaction': constraint_satisfaction,
            'predicted_performance': predicted_performance,
            'risk_assessment': risk_assessment
        }

    def _calculate_team_performance_score(self, team_members: List[str], requirements: List[CapabilityRequirement]) -> float:
        """Calculate overall team performance score"""
        if not team_members:
            return 0.0

        # Individual performance scores
        individual_scores = []
        for agent in team_members:
            profile = self.agent_profiles[agent]
            agent_score = (
                profile.performance_metrics['throughput'] * 0.3 +
                profile.performance_metrics['reliability'] * 0.3 +
                profile.performance_metrics['efficiency'] * 0.2 +
                profile.performance_metrics['adaptability'] * 0.2
            )
            individual_scores.append(agent_score)

        # Team synergy bonus
        synergy_bonus = self._calculate_team_synergy(team_members)

        # Capability coverage score
        coverage_score = self._calculate_capability_coverage(team_members, requirements)

        # Combine scores
        base_performance = np.mean(individual_scores)
        total_performance = min(1.0, base_performance * (1.0 + synergy_bonus) * coverage_score)

        return total_performance

    def _calculate_team_synergy(self, team_members: List[str]) -> float:
        """Calculate team synergy based on agent compatibility"""
        if len(team_members) < 2:
            return 0.0

        synergy_scores = []
        for i, agent1 in enumerate(team_members):
            for agent2 in team_members[i+1:]:
                compatibility = self.agent_profiles[agent1].collaboration_scores.get(agent2, 0.5)
                synergy_scores.append(compatibility)

        return np.mean(synergy_scores) - 0.5  # Bonus above neutral compatibility

    def _calculate_capability_coverage(self, team_members: List[str], requirements: List[CapabilityRequirement]) -> float:
        """Calculate how well the team covers required capabilities"""
        if not requirements:
            return 1.0

        coverage_scores = []
        for req in requirements:
            # Find best coverage for this capability in the team
            best_coverage = 0.0
            for agent in team_members:
                agent_level = self.agent_profiles[agent].capabilities.get(req.capability_name, 0.0)
                coverage = min(1.0, agent_level / req.required_level) if req.required_level > 0 else 1.0
                best_coverage = max(best_coverage, coverage)

            # Weight by requirement importance
            weighted_coverage = best_coverage * req.weight
            coverage_scores.append(weighted_coverage)

        return np.mean(coverage_scores)

    def analyze_workload_distribution(self, team_composition: Dict[str, List[str]]) -> WorkloadDistribution:
        """Analyze workload distribution across team members"""

        all_members = sum(team_composition.values(), [])
        agent_workloads = {}

        # Calculate current workloads (would be based on active tasks in real implementation)
        for agent in all_members:
            profile = self.agent_profiles[agent]
            current_load = 0.5  # Placeholder - would be calculated from actual task assignments
            capacity = profile.workload_capacity
            utilization = current_load / capacity if capacity > 0 else 1.0
            agent_workloads[agent] = utilization

        # Calculate load balance score
        workload_values = list(agent_workloads.values())
        if workload_values:
            load_variance = np.var(workload_values)
            load_balance_score = max(0.0, 1.0 - load_variance)
        else:
            load_balance_score = 1.0

        # Identify bottlenecks and underutilized agents
        bottleneck_agents = [agent for agent, load in agent_workloads.items() if load > 0.8]
        underutilized_agents = [agent for agent, load in agent_workloads.items() if load < 0.3]

        # Generate redistribution suggestions
        redistribution_suggestions = []
        for bottleneck in bottleneck_agents:
            for underutilized in underutilized_agents:
                # Check if underutilized agent can help with bottleneck's work
                suggestion = {
                    'from_agent': bottleneck,
                    'to_agent': underutilized,
                    'workload_transfer': 0.2,  # Suggest transferring 20% of workload
                    'feasibility_score': self._calculate_transfer_feasibility(bottleneck, underutilized)
                }
                redistribution_suggestions.append(suggestion)

        return WorkloadDistribution(
            agent_workloads=agent_workloads,
            load_balance_score=load_balance_score,
            bottleneck_agents=bottleneck_agents,
            underutilized_agents=underutilized_agents,
            redistribution_suggestions=redistribution_suggestions
        )

    def recommend_team_improvements(self,
                                  current_team: Dict[str, List[str]],
                                  performance_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Recommend improvements to current team composition"""

        recommendations = []
        all_members = sum(current_team.values(), [])

        # Analyze current performance
        workload_analysis = self.analyze_workload_distribution(current_team)

        # Recommendation 1: Address workload imbalances
        if workload_analysis.load_balance_score < 0.7:
            recommendations.append({
                'type': 'workload_rebalancing',
                'priority': 'high',
                'description': 'Rebalance workload distribution to improve team efficiency',
                'specific_actions': workload_analysis.redistribution_suggestions[:3],
                'expected_improvement': '15-25% efficiency gain'
            })

        # Recommendation 2: Capability gaps
        capability_gaps = self._identify_capability_gaps(all_members)
        if capability_gaps:
            recommendations.append({
                'type': 'capability_enhancement',
                'priority': 'medium',
                'description': 'Address capability gaps through training or team augmentation',
                'specific_actions': [
                    {
                        'action': 'training',
                        'agent': agent,
                        'capability': gap['capability'],
                        'current_level': gap['current_level'],
                        'target_level': gap['target_level']
                    }
                    for agent in all_members
                    for gap in capability_gaps
                ],
                'expected_improvement': '10-20% quality improvement'
            })

        # Recommendation 3: Team composition optimization
        if len(all_members) > 6:  # Large team
            recommendations.append({
                'type': 'team_restructuring',
                'priority': 'medium',
                'description': 'Consider splitting into smaller, more focused sub-teams',
                'specific_actions': self._suggest_team_splits(current_team),
                'expected_improvement': 'Better coordination and faster delivery'
            })

        # Recommendation 4: Performance optimization
        low_performers = [agent for agent in all_members
                         if self.agent_profiles[agent].performance_metrics['reliability'] < 0.7]
        if low_performers:
            recommendations.append({
                'type': 'performance_improvement',
                'priority': 'high',
                'description': 'Address performance issues with specific agents',
                'specific_actions': [
                    {
                        'agent': agent,
                        'current_performance': self.agent_profiles[agent].performance_metrics['reliability'],
                        'improvement_plan': self._generate_improvement_plan(agent)
                    }
                    for agent in low_performers
                ],
                'expected_improvement': '20-30% overall team performance'
            })

        return recommendations

    # Additional helper methods for calculations and analysis
    def _filter_available_agents(self, constraints: List[OptimizationConstraint]) -> List[str]:
        """Filter agents based on availability and constraints"""
        available = []
        for agent_name, profile in self.agent_profiles.items():
            if profile.availability_probability > 0.5:  # At least 50% availability
                available.append(agent_name)
        return available

    def _generate_performance_driven_teams(self, available_agents: List[str], team_size_range: Tuple[int, int]) -> List[Dict[str, List[str]]]:
        """Generate teams optimized for performance"""
        # Sort agents by performance
        agent_scores = [(agent, self.agent_profiles[agent].performance_metrics['reliability'])
                       for agent in available_agents]
        agent_scores.sort(key=lambda x: x[1], reverse=True)

        teams = []
        for size in range(team_size_range[0], min(team_size_range[1] + 1, len(available_agents) + 1)):
            top_agents = [agent for agent, _ in agent_scores[:size]]
            team = {
                'lead': [top_agents[0]] if top_agents else [],
                'specialists': top_agents[1:max(1, size-2)] if len(top_agents) > 2 else [],
                'support': top_agents[max(1, size-2):] if len(top_agents) > 2 else top_agents[1:]
            }
            teams.append(team)

        return teams

    def _generate_balanced_teams(self, available_agents: List[str], requirements: List[CapabilityRequirement], team_size_range: Tuple[int, int]) -> List[Dict[str, List[str]]]:
        """Generate balanced teams considering multiple factors"""
        # This would implement a more sophisticated balanced selection algorithm
        # For now, return a simple implementation
        return self._generate_performance_driven_teams(available_agents, team_size_range)

    # More helper methods would be implemented here...
    def _calculate_team_cost_score(self, team_members: List[str]) -> float:
        """Calculate team cost score (higher is better = lower cost)"""
        total_cost = sum(self.agent_profiles[agent].cost_per_hour for agent in team_members)
        # Normalize to 0-1 scale (assuming max reasonable cost)
        max_reasonable_cost = len(team_members) * 100  # $100/hour per agent
        cost_score = max(0.0, 1.0 - (total_cost / max_reasonable_cost))
        return cost_score

    def _calculate_team_reliability_score(self, team_members: List[str]) -> float:
        """Calculate team reliability score"""
        individual_reliability = [self.agent_profiles[agent].performance_metrics['reliability']
                                for agent in team_members]
        return np.mean(individual_reliability)

    def _calculate_team_time_score(self, team_members: List[str]) -> float:
        """Calculate team time efficiency score"""
        throughput_scores = [self.agent_profiles[agent].performance_metrics['throughput']
                           for agent in team_members]
        return np.mean(throughput_scores)

    def _calculate_team_quality_score(self, team_members: List[str], requirements: List[CapabilityRequirement]) -> float:
        """Calculate team quality score based on capability depth"""
        quality_scores = []
        for req in requirements:
            agent_qualities = [self.agent_profiles[agent].capabilities.get(req.capability_name, 0.0)
                             for agent in team_members]
            max_quality = max(agent_qualities) if agent_qualities else 0.0
            quality_scores.append(max_quality)

        return np.mean(quality_scores) if quality_scores else 0.0

    def _evaluate_constraint_satisfaction(self, team_members: List[str], constraint: OptimizationConstraint) -> float:
        """Evaluate how well the team satisfies a specific constraint"""
        if constraint.constraint_type == ConstraintType.BUDGET_LIMIT:
            total_cost = sum(self.agent_profiles[agent].cost_per_hour for agent in team_members)
            return 1.0 if total_cost <= constraint.target_value else 0.0
        elif constraint.constraint_type == ConstraintType.RESOURCE_LIMIT:
            # Simplified resource check
            return 1.0  # Would implement actual resource checking
        else:
            return 1.0  # Default satisfaction

    def _predict_team_performance(self, team_members: List[str], requirements: List[CapabilityRequirement]) -> Dict[str, float]:
        """Predict team performance metrics"""
        return {
            'success_probability': self._calculate_team_reliability_score(team_members),
            'estimated_completion_time': len(requirements) * 2.0,  # Simplified
            'quality_score': self._calculate_team_quality_score(team_members, requirements),
            'efficiency_score': np.mean([self.agent_profiles[agent].performance_metrics['efficiency']
                                       for agent in team_members])
        }

    def _assess_team_risks(self, team_members: List[str]) -> Dict[str, float]:
        """Assess various risks for the team composition"""
        return {
            'single_point_of_failure': self._calculate_spof_risk(team_members),
            'skill_concentration_risk': self._calculate_skill_concentration_risk(team_members),
            'communication_overhead': self._calculate_communication_overhead(team_members),
            'availability_risk': self._calculate_availability_risk(team_members)
        }

    def _generate_recommendations(self, team: Dict[str, List[str]], evaluation: Dict[str, Any]) -> List[str]:
        """Generate specific recommendations for the team"""
        recommendations = []

        if evaluation['total_score'] < 0.7:
            recommendations.append("Consider alternative team compositions for better performance")

        # Add more specific recommendations based on evaluation results
        risk_assessment = evaluation.get('risk_assessment', {})
        if risk_assessment.get('single_point_of_failure', 0.0) > 0.7:
            recommendations.append("Add backup agents for critical capabilities to reduce single point of failure risk")

        if risk_assessment.get('communication_overhead', 0.0) > 0.8:
            recommendations.append("Team size may be too large - consider breaking into smaller sub-teams")

        return recommendations

    # Placeholder implementations for remaining helper methods
    def _calculate_efficiency_score(self, agent_name: str) -> float:
        """Calculate agent efficiency score based on success rate and execution time"""
        agent = self.agents[agent_name]
        # Base efficiency from success rate
        base_efficiency = agent.success_rate
        # Adjust for execution time (faster is better, normalized)
        time_factor = 1.0 / (1.0 + agent.average_execution_time / 3600.0)  # Normalize by hour
        return min(1.0, base_efficiency * time_factor)

    def _calculate_adaptability_score(self, agent_name: str) -> float:
        """Calculate agent adaptability score based on capability diversity and success across different task types"""
        agent = self.agents[agent_name]
        profile = self.agent_profiles.get(agent_name)
        
        if not profile:
            # Fallback: use capability count as proxy
            capability_diversity = min(1.0, len(agent.capabilities) / 10.0)
            return capability_diversity * agent.success_rate
        
        # Adaptability = capability breadth * success rate * specialization balance
        capability_breadth = len(profile.capabilities) / max(1, len(self.agent_profiles))
        specialization_balance = 1.0 - abs(profile.specialization_breadth - 0.5) * 2  # Prefer balanced agents
        success_factor = agent.success_rate
        
        return min(1.0, (capability_breadth * 0.4 + specialization_balance * 0.3 + success_factor * 0.3))

    def _estimate_agent_cost(self, agent_name: str) -> float:
        """Estimate agent cost per hour"""
        agent = self.agents[agent_name]
        base_cost = 50.0  # Base cost
        complexity_multiplier = len(agent.capabilities) * 5.0
        return base_cost + complexity_multiplier

    def _calculate_availability_probability(self, agent_name: str) -> float:
        """Calculate agent availability probability based on success rate and historical data"""
        agent = self.agents[agent_name]
        
        # Base availability from success rate
        base_availability = agent.success_rate
        
        # Adjust based on historical data if available
        if self.historical_data and agent_name in self.historical_data:
            hist = self.historical_data[agent_name]
            uptime = hist.get('uptime', base_availability)
            recent_success = hist.get('recent_success_rate', base_availability)
            # Weight recent performance more heavily
            return min(1.0, (uptime * 0.3 + recent_success * 0.7))
        
        # Default: success rate with conservative adjustment
        return min(1.0, base_availability * 0.95)

    def _estimate_learning_rate(self, agent_name: str) -> float:
        """Estimate agent learning rate based on performance improvement over time"""
        agent = self.agents[agent_name]
        
        # Check historical data for improvement trends
        if self.historical_data and agent_name in self.historical_data:
            hist = self.historical_data[agent_name]
            improvement_trend = hist.get('improvement_trend', 0.0)
            # Normalize improvement trend to 0-1 range
            return min(1.0, max(0.0, improvement_trend))
        
        # Estimate based on agent characteristics
        # Agents with diverse capabilities tend to learn faster
        capability_count = len(agent.capabilities)
        diversity_factor = min(1.0, capability_count / 10.0)
        
        # Success rate indicates ability to learn from mistakes
        success_factor = agent.success_rate
        
        # Base learning rate calculation
        return min(1.0, (diversity_factor * 0.6 + success_factor * 0.4) * 0.3)

    def _estimate_stress_tolerance(self, agent_name: str) -> float:
        """Estimate agent stress tolerance based on concurrent task capacity and performance under load"""
        agent = self.agents[agent_name]
        profile = self.agent_profiles.get(agent_name)
        
        # Base tolerance from concurrent task capacity
        capacity_factor = min(1.0, agent.max_concurrent_tasks / 10.0)
        
        # Success rate under load (if historical data available)
        if self.historical_data and agent_name in self.historical_data:
            hist = self.historical_data[agent_name]
            high_load_success = hist.get('high_load_success_rate', agent.success_rate)
            load_factor = high_load_success
        else:
            load_factor = agent.success_rate
        
        # Execution time consistency (lower variance = better stress tolerance)
        if agent.average_execution_time > 0:
            time_consistency = 1.0 / (1.0 + agent.average_execution_time / 3600.0)
        else:
            time_consistency = 0.8
        
        # Combine factors
        return min(1.0, (capacity_factor * 0.4 + load_factor * 0.4 + time_consistency * 0.2))

    def _calculate_specialization_breadth(self, agent_name: str) -> float:
        """Calculate specialization vs generalization score"""
        agent = self.agents[agent_name]
        return min(1.0, len(agent.capabilities) / 10.0)

    def _train_prediction_models(self):
        """Train ML models for performance prediction using historical data"""
        if OPTIMIZATION_LIBS_AVAILABLE:
            self.performance_predictor = RandomForestRegressor(n_estimators=100)
            # Train with historical data if available
            if self.historical_data and len(self.historical_data) > 5:
                # Prepare training data from historical performance
                X, y = self._prepare_training_data()
                if len(X) > 0:
                    self.performance_predictor.fit(X, y)
                    self.logger.info("Performance prediction model trained successfully")

    def _calculate_spof_risk(self, team_members: List[str]) -> float:
        """Calculate single point of failure risk based on critical capability concentration"""
        if len(team_members) <= 1:
            return 1.0  # Single agent = high SPOF risk
        
        # Identify critical capabilities (required by tasks but held by few agents)
        all_capabilities = set()
        capability_holders = defaultdict(list)
        
        for agent_name in team_members:
            agent = self.agents.get(agent_name)
            if agent:
                for cap in agent.capabilities:
                    all_capabilities.add(cap)
                    capability_holders[cap].append(agent_name)
        
        # Calculate risk: capabilities held by only one agent
        critical_capabilities = 0
        for cap, holders in capability_holders.items():
            if len(holders) == 1:
                critical_capabilities += 1
        
        # Risk increases with critical capability concentration
        if len(all_capabilities) > 0:
            concentration_risk = critical_capabilities / len(all_capabilities)
        else:
            concentration_risk = 0.0
        
        # Team size factor (smaller teams = higher SPOF risk)
        size_risk = 1.0 / max(1, len(team_members))
        
        return min(1.0, (concentration_risk * 0.7 + size_risk * 0.3))

    def _calculate_skill_concentration_risk(self, team_members: List[str]) -> float:
        """Calculate skill concentration risk based on capability distribution across team"""
        if len(team_members) <= 1:
            return 0.0  # No concentration risk with single agent
        
        # Collect all capabilities and their distribution
        capability_distribution = defaultdict(int)
        total_capabilities = 0
        
        for agent_name in team_members:
            agent = self.agents.get(agent_name)
            if agent:
                for cap in agent.capabilities:
                    capability_distribution[cap] += 1
                    total_capabilities += 1
        
        if total_capabilities == 0:
            return 0.0
        
        # Calculate Gini coefficient for capability distribution
        # Higher Gini = more concentration = higher risk
        capability_counts = sorted(capability_distribution.values())
        n = len(capability_counts)
        
        if n == 0:
            return 0.0
        
        # Simplified Gini calculation
        cumsum = 0
        for i, count in enumerate(capability_counts):
            cumsum += count * (i + 1)
        
        gini = (2 * cumsum) / (n * sum(capability_counts)) - (n + 1) / n
        gini = max(0.0, min(1.0, gini))  # Normalize to 0-1
        
        return gini

    def _calculate_communication_overhead(self, team_members: List[str]) -> float:
        """Calculate communication overhead based on team size"""
        team_size = len(team_members)
        # Communication complexity grows quadratically
        return min(1.0, (team_size * (team_size - 1)) / 50.0)

    def _calculate_availability_risk(self, team_members: List[str]) -> float:
        """Calculate overall availability risk"""
        availability_probs = [self.agent_profiles[agent].availability_probability
                            for agent in team_members]
        overall_availability = np.prod(availability_probs)
        return 1.0 - overall_availability

    def _identify_capability_gaps(self, team_members: List[str]) -> List[Dict[str, Any]]:
        """Identify capability gaps in the team based on required vs available capabilities"""
        gaps = []
        
        # Collect team capabilities
        team_capabilities = set()
        for agent_name in team_members:
            agent = self.agents.get(agent_name)
            if agent:
                team_capabilities.update(agent.capabilities)
        
        # Check against known capability requirements (if available)
        if hasattr(self, 'capability_requirements') and self.capability_requirements:
            for req in self.capability_requirements:
                req_cap = req.capability_name
                if req_cap not in team_capabilities:
                    gaps.append({
                        'capability': req_cap,
                        'required_level': req.required_level,
                        'is_critical': req.is_critical,
                        'severity': 'critical' if req.is_critical else 'moderate',
                        'suggested_agents': self._find_agents_with_capability(req_cap)
                    })
        
        # Also identify weak capabilities (low proficiency)
        for agent_name in team_members:
            agent = self.agents.get(agent_name)
            if agent:
                profile = self.agent_profiles.get(agent_name)
                if profile:
                    for cap, level in profile.capabilities.items():
                        if level < 0.5:  # Low proficiency threshold
                            gaps.append({
                                'capability': cap,
                                'current_level': level,
                                'agent': agent_name,
                                'severity': 'low',
                                'suggestion': 'Improve proficiency or add specialist'
                            })
        
        return gaps

    def _suggest_team_splits(self, current_team: Dict[str, List[str]]) -> List[Dict[str, Any]]:
        """Suggest how to split large teams based on communication overhead and capability distribution"""
        suggestions = []
        
        for role, agents in current_team.items():
            if len(agents) <= 4:  # No need to split small teams
                continue
            
            # Calculate communication overhead
            overhead = self._calculate_communication_overhead(agents)
            
            if overhead > 0.7:  # High overhead threshold
                # Suggest split based on capability clusters
                capability_clusters = self._cluster_agents_by_capabilities(agents)
                
                if len(capability_clusters) > 1:
                    suggestions.append({
                        'role': role,
                        'current_size': len(agents),
                        'recommended_splits': len(capability_clusters),
                        'clusters': capability_clusters,
                        'reason': 'High communication overhead and natural capability clusters',
                        'expected_overhead_reduction': overhead - 0.3
                    })
                else:
                    # Split evenly if no natural clusters
                    split_size = max(2, len(agents) // 2)
                    suggestions.append({
                        'role': role,
                        'current_size': len(agents),
                        'recommended_splits': 2,
                        'split_size': split_size,
                        'reason': 'High communication overhead, suggest even split',
                        'expected_overhead_reduction': overhead * 0.5
                    })
        
        return suggestions

    def _generate_improvement_plan(self, agent: str) -> Dict[str, Any]:
        """Generate improvement plan for underperforming agent based on performance gaps"""
        agent_obj = self.agents.get(agent)
        profile = self.agent_profiles.get(agent)
        
        if not agent_obj:
            return {'error': 'Agent not found'}
        
        plan = {
            'agent': agent,
            'training': [],
            'mentoring': False,
            'resource_allocation': {},
            'timeline': '4-6 weeks'
        }
        
        # Identify performance gaps
        if agent_obj.success_rate < 0.8:
            plan['training'].append('error_handling')
            plan['training'].append('quality_assurance')
        
        if agent_obj.average_execution_time > 3600:  # > 1 hour
            plan['training'].append('performance_optimization')
            plan['resource_allocation']['compute'] = 'increase'
        
        if profile:
            # Identify weak capabilities
            weak_caps = [cap for cap, level in profile.capabilities.items() if level < 0.6]
            if weak_caps:
                plan['training'].extend([f'capability_{cap}' for cap in weak_caps[:3]])  # Top 3
        
        # Suggest mentoring if success rate is very low
        if agent_obj.success_rate < 0.7:
            plan['mentoring'] = True
            plan['mentor_criteria'] = 'High-performing agent with similar capabilities'
        
        # Resource recommendations
        if agent_obj.max_concurrent_tasks < 3:
            plan['resource_allocation']['concurrency'] = 'increase'
        
        if not plan['training']:
            plan['training'] = ['general_performance']
        
        return plan

    def _calculate_transfer_feasibility(self, from_agent: str, to_agent: str) -> float:
        """Calculate feasibility of transferring work between agents based on capability overlap"""
        agent1 = self.agents.get(from_agent)
        agent2 = self.agents.get(to_agent)
        
        if not agent1 or not agent2:
            return 0.0
        
        # Calculate capability overlap
        caps1 = set(agent1.capabilities)
        caps2 = set(agent2.capabilities)
        
        if not caps1:
            return 0.0
        
        # Jaccard similarity for capability overlap
        intersection = caps1 & caps2
        union = caps1 | caps2
        overlap = len(intersection) / len(union) if union else 0.0
        
        # Consider success rates (both should be capable)
        success_factor = min(agent1.success_rate, agent2.success_rate)
        
        # Consider specialization (generalists transfer better)
        profile1 = self.agent_profiles.get(from_agent)
        profile2 = self.agent_profiles.get(to_agent)
        
        specialization_factor = 1.0
        if profile1 and profile2:
            # Average specialization breadth (higher = more generalist = easier transfer)
            avg_breadth = (profile1.specialization_breadth + profile2.specialization_breadth) / 2.0
            specialization_factor = avg_breadth
        
        # Combined feasibility score
        return min(1.0, (overlap * 0.5 + success_factor * 0.3 + specialization_factor * 0.2))
    
    def _find_agents_with_capability(self, capability: str) -> List[str]:
        """Find all agents that have a specific capability"""
        matching_agents = []
        for agent_name, agent in self.agents.items():
            if capability in agent.capabilities:
                matching_agents.append(agent_name)
        return matching_agents
    
    def _cluster_agents_by_capabilities(self, agents: List[str]) -> List[List[str]]:
        """Cluster agents by similar capability sets"""
        if len(agents) <= 1:
            return [agents]
        
        # Build capability vectors for each agent
        agent_caps = {}
        all_caps = set()
        
        for agent_name in agents:
            agent = self.agents.get(agent_name)
            if agent:
                caps = set(agent.capabilities)
                agent_caps[agent_name] = caps
                all_caps.update(caps)
        
        if not all_caps:
            return [agents]
        
        # Simple clustering: group agents with high capability overlap
        clusters = []
        remaining = set(agents)
        
        while remaining:
            # Start new cluster with first remaining agent
            seed = list(remaining)[0]
            cluster = [seed]
            remaining.remove(seed)
            seed_caps = agent_caps.get(seed, set())
            
            # Find similar agents
            for agent_name in list(remaining):
                agent_caps_set = agent_caps.get(agent_name, set())
                # Calculate overlap
                if seed_caps and agent_caps_set:
                    overlap = len(seed_caps & agent_caps_set) / len(seed_caps | agent_caps_set)
                    if overlap > 0.5:  # 50% overlap threshold
                        cluster.append(agent_name)
                        remaining.remove(agent_name)
            
            clusters.append(cluster)
        
        return clusters if clusters else [agents]
    
    def _prepare_training_data(self) -> Tuple[List[List[float]], List[float]]:
        """Prepare training data for ML models from historical data"""
        X = []
        y = []
        
        for agent_name, hist in self.historical_data.items():
            if agent_name not in self.agents:
                continue
            
            agent = self.agents[agent_name]
            features = [
                len(agent.capabilities),
                agent.success_rate,
                agent.max_concurrent_tasks,
                agent.average_execution_time / 3600.0,  # Normalize to hours
                hist.get('uptime', 0.9),
                hist.get('recent_success_rate', agent.success_rate),
            ]
            X.append(features)
            y.append(hist.get('performance_score', agent.success_rate))
        
        return X, y


# Example usage and testing
async def main():
    """Example usage of the optimization engine"""
    # This would be integrated with the actual SPECTRA system
    print("SPECTRA Agent Team Optimization Engine")
    print("=" * 50)

    # Example agent data (would come from actual orchestrator)
    example_agents = {
        'DIRECTOR': AgentMetadata(
            name='DIRECTOR',
            category='command_control',
            capabilities=['strategic_planning', 'resource_allocation'],
            max_concurrent_tasks=2,
            success_rate=0.95
        ),
        'DATABASE': AgentMetadata(
            name='DATABASE',
            category='infrastructure',
            capabilities=['schema_design', 'optimization'],
            max_concurrent_tasks=1,
            success_rate=0.90
        ),
        'OPTIMIZER': AgentMetadata(
            name='OPTIMIZER',
            category='performance',
            capabilities=['performance_tuning', 'compression'],
            max_concurrent_tasks=2,
            success_rate=0.88
        )
    }

    # Initialize optimization engine
    engine = AgentOptimizationEngine(example_agents)

    # Example optimization
    requirements = [
        CapabilityRequirement(
            capability_name='strategic_planning',
            required_level=0.8,
            weight=1.0,
            is_critical=True
        ),
        CapabilityRequirement(
            capability_name='schema_design',
            required_level=0.7,
            weight=0.8,
            is_critical=False
        )
    ]

    constraints = [
        OptimizationConstraint(
            constraint_type=ConstraintType.BUDGET_LIMIT,
            target_value=500.0,  # $500/hour budget
            is_hard_constraint=True
        )
    ]

    # Optimize team
    try:
        result = engine.optimize_team_composition(
            requirements=requirements,
            constraints=constraints,
            objective=OptimizationObjective.BALANCED_APPROACH
        )

        print(f"Optimized Team Composition:")
        print(f"Total Score: {result.total_score:.3f}")
        print(f"Team: {result.team_composition}")
        print(f"Recommendations: {result.recommendations}")

    except Exception as e:
        print(f"Optimization failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())