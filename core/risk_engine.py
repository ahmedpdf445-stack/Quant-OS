"""
Quantum Approximate Optimization Algorithm (QAOA) Portfolio Balance Core
Simulates quantum adiabatic state spaces for portfolio weight optimization
Compiled with Numba @njit for ultra-high-performance quantum simulation
"""

import numpy as np
from numba import njit
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


@njit(fastmath=True, cache=True)
def compute_qaoa_cost_hamiltonian(weights: np.ndarray, returns: np.ndarray,
                                   cov_matrix: np.ndarray, risk_penalty: float) -> float:
    """
    Compute cost Hamiltonian for portfolio optimization
    H_C = -w^T * returns + λ * (w^T * Σ * w)
    
    Args:
        weights: Portfolio weight vector (must sum to 1.0)
        returns: Expected returns vector
        cov_matrix: Covariance matrix of returns
        risk_penalty: Risk aversion parameter λ
    
    Returns:
        Cost Hamiltonian value
    """
    n = len(weights)
    
    # Defensive checks
    if n == 0 or n != len(returns):
        return 0.0
    
    if cov_matrix.shape[0] != n or cov_matrix.shape[1] != n:
        return 0.0
    
    # Clip weights to valid range (manual clip for Numba compatibility)
    weights_clipped = np.zeros_like(weights)
    for i in range(n):
        w = weights[i]
        weights_clipped[i] = max(0.0, min(1.0, w))
    
    # Normalize weights to sum to 1.0
    weights_sum = 0.0
    for i in range(n):
        weights_sum += weights_clipped[i]
    
    if weights_sum > 1e-10:
        for i in range(n):
            weights_clipped[i] /= weights_sum
    else:
        # Equal weight if all weights are zero
        for i in range(n):
            weights_clipped[i] = 1.0 / n
    
    # Expected return term (to maximize, negate in cost function)
    expected_return = 0.0
    for i in range(n):
        expected_return += weights_clipped[i] * returns[i]
    
    # Portfolio variance term
    portfolio_var = 0.0
    for i in range(n):
        for j in range(n):
            portfolio_var += weights_clipped[i] * cov_matrix[i, j] * weights_clipped[j]
    
    # Cost Hamiltonian (negative return + risk penalty on variance)
    cost = -expected_return + risk_penalty * portfolio_var
    
    return cost


@njit(fastmath=True, cache=True)
def qaoa_phase_gate(state_vector: np.ndarray, gamma: float, 
                    hamiltonian_energies: np.ndarray) -> np.ndarray:
    """
    Apply QAOA phase gate: |ψ⟩ → exp(-i*γ*H) |ψ⟩
    Simulates adiabatic evolution under problem Hamiltonian
    
    Args:
        state_vector: Current quantum state (complex amplitudes)
        gamma: Phase angle parameter
        hamiltonian_energies: Diagonal Hamiltonian matrix values
    
    Returns:
        Updated state vector after phase gate
    """
    n = len(state_vector)
    new_state = np.zeros_like(state_vector)
    
    for i in range(n):
        # exp(-i*γ*E_i) = cos(γ*E_i) - i*sin(γ*E_i)
        phase_angle = gamma * hamiltonian_energies[i]
        
        # Defensive check for numerical stability
        if abs(phase_angle) > 100.0:
            phase_angle = np.sign(phase_angle) * 100.0
        
        cos_phase = np.cos(phase_angle)
        sin_phase = np.sin(phase_angle)
        
        # Apply phase: complex multiplication
        real_part = state_vector[i].real * cos_phase - state_vector[i].imag * (-sin_phase)
        imag_part = state_vector[i].real * (-sin_phase) + state_vector[i].imag * cos_phase
        
        new_state[i] = real_part + 1j * imag_part
    
    return new_state


@njit(fastmath=True, cache=True)
def qaoa_mixer_gate(state_vector: np.ndarray, beta: float) -> np.ndarray:
    """
    Apply QAOA mixer gate: exp(-i*β*H_mixer)
    Mixer Hamiltonian is typically the sum of Pauli-X operators
    
    Args:
        state_vector: Current quantum state
        beta: Mixer angle parameter
    
    Returns:
        Updated state vector after mixer gate
    """
    n = len(state_vector)
    new_state = np.zeros_like(state_vector)
    
    # Simplified mixer: applies rotation-like transformation
    cos_beta = np.cos(beta)
    sin_beta = np.sin(beta)
    
    for i in range(n):
        # Pair-wise mixing (simplified)
        new_state[i] = cos_beta * state_vector[i] + sin_beta * state_vector[(i + 1) % n]
    
    return new_state


@njit(fastmath=True, cache=True)
def qaoa_circuit(initial_state: np.ndarray, gamma_angles: np.ndarray,
                 beta_angles: np.ndarray, hamiltonian_energies: np.ndarray,
                 depth: int) -> np.ndarray:
    """
    Execute complete QAOA circuit with alternating phase and mixer gates
    
    Args:
        initial_state: Initial uniform superposition state
        gamma_angles: Array of gamma parameters (length = depth)
        beta_angles: Array of beta parameters (length = depth)
        hamiltonian_energies: Diagonal Hamiltonian values
        depth: Circuit depth (must match length of gamma_angles)
    
    Returns:
        Final quantum state after full circuit
    """
    state = np.array(initial_state, dtype=np.complex128)
    
    # Normalize initial state
    norm = 0.0
    for i in range(len(state)):
        norm += abs(state[i]) ** 2
    norm = np.sqrt(norm) if norm > 1e-10 else 1.0
    
    for i in range(len(state)):
        state[i] /= norm
    
    # Apply p layers of (phase gate + mixer gate)
    for layer in range(min(depth, len(gamma_angles), len(beta_angles))):
        gamma = gamma_angles[layer]
        beta = beta_angles[layer]
        
        # Apply phase gate
        state = qaoa_phase_gate(state, gamma, hamiltonian_energies)
        
        # Apply mixer gate
        state = qaoa_mixer_gate(state, beta)
    
    return state


@njit(fastmath=True, cache=True)
def compute_portfolio_weights_from_state(state_vector: np.ndarray, n_assets: int) -> np.ndarray:
    """
    Extract portfolio weights from quantum state vector
    Weights are proportional to squared amplitudes (probabilities)
    
    Args:
        state_vector: Final quantum state
        n_assets: Number of portfolio assets
    
    Returns:
        Normalized portfolio weight vector
    """
    if len(state_vector) < n_assets:
        logger.warning("State vector size insufficient for number of assets")
        return np.ones(n_assets) / n_assets
    
    # Compute probabilities from amplitudes
    probabilities = np.zeros(n_assets)
    for i in range(n_assets):
        amp = state_vector[i]
        prob = (amp.real * amp.real) + (amp.imag * amp.imag)
        probabilities[i] = prob
    
    # Normalize to sum to 1.0
    prob_sum = 0.0
    for i in range(n_assets):
        prob_sum += probabilities[i]
    
    weights = np.zeros(n_assets)
    if prob_sum > 1e-10:
        for i in range(n_assets):
            weights[i] = probabilities[i] / prob_sum
    else:
        # Default: equal weights
        for i in range(n_assets):
            weights[i] = 1.0 / n_assets
    
    return weights


class QAOAOptimizer:
    """Quantum Approximate Optimization Algorithm for portfolio management"""
    
    def __init__(self, depth: int = 5, learning_rate: float = 0.01):
        self.depth = depth
        self.learning_rate = learning_rate
        self.gamma_params = np.ones(depth) * 0.5
        self.beta_params = np.ones(depth) * 0.5
        self.optimization_history = []
        logger.info(f"QAOAOptimizer initialized: depth={depth}, lr={learning_rate}")
    
    def optimize_portfolio(self, returns: np.ndarray, cov_matrix: np.ndarray,
                          risk_aversion: float = 1.0, iterations: int = 50) -> np.ndarray:
        """
        Optimize portfolio weights using QAOA
        
        Args:
            returns: Expected returns for each asset
            cov_matrix: Covariance matrix
            risk_aversion: Risk penalty parameter
            iterations: Number of optimization iterations
        
        Returns:
            Optimized portfolio weights
        """
        n_assets = len(returns)
        
        if n_assets == 0 or cov_matrix.shape[0] != n_assets:
            logger.error("Invalid input dimensions")
            return np.ones(n_assets if n_assets > 0 else 1) / max(n_assets, 1)
        
        # Initialize uniform superposition state
        initial_state = np.ones(n_assets, dtype=np.complex128) / np.sqrt(n_assets)
        
        # Compute Hamiltonian energies (cost values for each basis state)
        hamiltonian_energies = np.zeros(n_assets)
        for i in range(n_assets):
            weights = np.zeros(n_assets)
            weights[i] = 1.0
            cost = compute_qaoa_cost_hamiltonian(weights, returns, cov_matrix, risk_aversion)
            hamiltonian_energies[i] = cost
        
        # Optimization loop
        best_cost = float('inf')
        best_weights = np.ones(n_assets) / n_assets
        
        for iteration in range(iterations):
            # Execute QAOA circuit
            final_state = qaoa_circuit(initial_state, self.gamma_params,
                                      self.beta_params, hamiltonian_energies, self.depth)
            
            # Extract weights from final state
            weights = compute_portfolio_weights_from_state(final_state, n_assets)
            
            # Evaluate cost
            cost = compute_qaoa_cost_hamiltonian(weights, returns, cov_matrix, risk_aversion)
            
            # Track optimization
            self.optimization_history.append(cost)
            
            # Update best solution
            if cost < best_cost:
                best_cost = cost
                best_weights = np.array(weights)
            
            # Simple parameter update (gradient-free)
            for i in range(self.depth):
                self.gamma_params[i] += self.learning_rate * np.sin(2 * self.gamma_params[i])
                self.beta_params[i] += self.learning_rate * np.cos(2 * self.beta_params[i])
        
        logger.info(f"QAOA optimization complete: final_cost={best_cost:.6f}")
        return best_weights
    
    def get_allocations(self, portfolio_value: float, weights: np.ndarray) -> np.ndarray:
        """Convert portfolio weights to dollar allocations with simplex constraint"""
        allocations = weights * portfolio_value
        
        # Ensure sum constraint is maintained
        allocation_sum = np.sum(allocations)
        if allocation_sum > 1e-10:
            allocations = allocations * (portfolio_value / allocation_sum)
        
        return allocations
