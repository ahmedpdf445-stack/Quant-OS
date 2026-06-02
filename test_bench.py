"""
Elite Quantitative Simulation Benchmark
10,000-path Monte Carlo simulator with Merton Jump Diffusion trajectories
Walk-Forward testing engine with advanced risk-aware metrics
"""

import numpy as np
import logging
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
import json

from config.settings import Settings
from core.regime_detector import RegimeDetector
from core.order_flow import HawkesPointProcess
from core.risk_engine import QAOAOptimizer
from agents.market_maker import MarketMakerAgent
from agents.directional import DirectionalAgent

logger = logging.getLogger(__name__)


class MonteCarloSimulator:
    """High-fidelity Monte Carlo simulator using Merton Jump Diffusion"""
    
    def __init__(self, n_paths: int = 10000, n_steps: int = 252):
        self.n_paths = n_paths
        self.n_steps = n_steps
        self.paths = None
        self.returns = None
        logger.info(f"Monte Carlo initialized: {n_paths} paths x {n_steps} steps")
    
    def generate_merton_paths(self, S0: float, mu: float, sigma: float,
                             jump_lambda: float, jump_mu: float, jump_sigma: float,
                             T: float = 1.0) -> np.ndarray:
        """
        Generate Merton Jump Diffusion price paths
        
        dS/S = μdt + σdW + Σ(dJ - λμ_j dt)
        
        Args:
            S0: Initial price
            mu: Drift coefficient
            sigma: Volatility
            jump_lambda: Jump intensity (events per year)
            jump_mu: Mean jump size
            jump_sigma: Jump standard deviation
            T: Time horizon (years)
        
        Returns:
            Array of shape (n_paths, n_steps) with price paths
        """
        dt = T / self.n_steps
        
        paths = np.zeros((self.n_paths, self.n_steps))
        paths[:, 0] = S0
        
        # Poisson jump times
        jump_times = np.random.poisson(jump_lambda * dt, size=(self.n_paths, self.n_steps))
        
        for t in range(1, self.n_steps):
            # Brownian motion
            dW = np.random.standard_normal(self.n_paths)
            
            # Gaussian jumps
            jump_sizes = np.random.normal(jump_mu, jump_sigma, size=self.n_paths)
            
            # Jump indicator
            has_jump = jump_times[:, t] > 0
            
            # Merton dynamics
            drift_component = (mu - 0.5 * sigma**2) * dt
            diffusion_component = sigma * np.sqrt(dt) * dW
            jump_component = np.where(has_jump, jump_sizes, 0)
            
            # Price update
            price_ratio = np.exp(drift_component + diffusion_component + jump_component)
            paths[:, t] = paths[:, t - 1] * price_ratio
            
            # Defensive check: prevent negative or NaN prices
            paths[:, t] = np.where(paths[:, t] > 0, paths[:, t], paths[:, t - 1])
        
        self.paths = paths
        self.returns = np.diff(paths, axis=1) / paths[:, :-1]
        
        return paths
    
    def compute_path_statistics(self) -> Dict:
        """Compute statistics across Monte Carlo paths"""
        if self.paths is None or len(self.paths) == 0:
            return {}
        
        final_prices = self.paths[:, -1]
        final_returns = (final_prices - self.paths[:, 0]) / self.paths[:, 0]
        
        stats = {
            'mean_final_price': float(np.mean(final_prices)),
            'median_final_price': float(np.median(final_prices)),
            'std_final_price': float(np.std(final_prices)),
            'min_final_price': float(np.min(final_prices)),
            'max_final_price': float(np.max(final_prices)),
            'mean_return': float(np.mean(final_returns)),
            'std_return': float(np.std(final_returns)),
            'var_95': float(np.percentile(final_returns, 5)),  # Value at Risk
            'cvar_95': float(np.mean(final_returns[final_returns <= np.percentile(final_returns, 5)])),
        }
        
        return stats


class WalkForwardEngine:
    """Advanced Walk-Forward testing with regime detection"""
    
    def __init__(self, window_size: int = 252, test_size: int = 63):
        self.window_size = window_size
        self.test_size = test_size
        self.results = []
        logger.info(f"WalkForwardEngine initialized: window={window_size}, test={test_size}")
    
    def compute_reward_metric(self, returns: np.ndarray, drawdown_max: float,
                            win_rate: float) -> float:
        """
        Institutional risk-aware reward metric
        
        Reward = Sharpe Ratio × Profit Factor - λ × (Max Drawdown)²
        
        Args:
            returns: Array of trading returns
            drawdown_max: Maximum drawdown experienced
            win_rate: Fraction of winning trades
        
        Returns:
            Composite reward score
        """
        if len(returns) < 2:
            return 0.0
        
        # Sharpe Ratio (annualized, assuming 252 trading days)
        mean_ret = np.mean(returns)
        std_ret = np.std(returns)
        
        if std_ret > 1e-10:
            sharpe = (mean_ret / std_ret) * np.sqrt(252)
        else:
            sharpe = 0.0
        
        # Profit Factor (ratio of winning to losing trades)
        winning_returns = returns[returns > 0]
        losing_returns = returns[returns < 0]
        
        if len(losing_returns) > 0 and len(winning_returns) > 0:
            profit_factor = np.sum(winning_returns) / np.abs(np.sum(losing_returns))
        elif len(winning_returns) > 0:
            profit_factor = np.abs(np.sum(winning_returns))
        else:
            profit_factor = 0.0
        
        # Drawdown penalty
        lambda_parameter = 2.0  # Risk penalty coefficient
        drawdown_penalty = lambda_parameter * (drawdown_max ** 2)
        
        # Composite reward
        reward = sharpe * profit_factor - drawdown_penalty
        
        return reward
    
    def run_walk_forward_test(self, prices: np.ndarray) -> Dict:
        """
        Execute complete walk-forward optimization and testing
        
        Args:
            prices: Full price time series
        
        Returns:
            Dictionary with test results and metrics
        """
        if prices is None or len(prices) < self.window_size + self.test_size:
            logger.error("Insufficient price data for walk-forward test")
            return {}
        
        n_windows = (len(prices) - self.window_size) // self.test_size
        
        all_returns = []
        all_metrics = []
        
        for window_idx in range(n_windows):
            # Split data
            train_start = window_idx * self.test_size
            train_end = train_start + self.window_size
            test_end = train_end + self.test_size
            
            if test_end > len(prices):
                break
            
            train_prices = prices[train_start:train_end]
            test_prices = prices[train_end:test_end]
            
            # Train regime detector on training window
            detector = RegimeDetector(window_bars=50)
            regimes, regime_metrics = detector.detect(train_prices)
            
            # Test on out-of-sample period
            test_regimes, test_metrics = detector.detect(test_prices)
            
            # Simulate trading returns
            test_returns = np.diff(test_prices) / test_prices[:-1]
            
            # Compute drawdown
            cumulative_returns = np.cumprod(1 + test_returns)
            running_max = np.maximum.accumulate(cumulative_returns)
            drawdown = (running_max - cumulative_returns) / running_max
            drawdown_max = np.max(drawdown)
            
            # Win rate
            win_count = np.sum(test_returns > 0)
            win_rate = win_count / len(test_returns) if len(test_returns) > 0 else 0.0
            
            # Compute reward
            reward = self.compute_reward_metric(test_returns, drawdown_max, win_rate)
            
            # Store results
            window_result = {
                'window_idx': window_idx,
                'train_period': f"{train_start}-{train_end}",
                'test_period': f"{train_end}-{test_end}",
                'cumulative_return': float(cumulative_returns[-1] - 1.0),
                'sharpe_ratio': float(np.mean(test_returns) / np.std(test_returns) * np.sqrt(252)) if np.std(test_returns) > 0 else 0,
                'max_drawdown': float(drawdown_max),
                'win_rate': float(win_rate),
                'reward_metric': float(reward),
                'avg_regime_state': float(np.mean(test_regimes)),
            }
            
            self.results.append(window_result)
            all_returns.append(test_returns)
            all_metrics.append(window_result)
        
        # Aggregate results
        if all_metrics:
            aggregated = {
                'n_windows': len(all_metrics),
                'avg_return': float(np.mean([m['cumulative_return'] for m in all_metrics])),
                'avg_sharpe': float(np.mean([m['sharpe_ratio'] for m in all_metrics])),
                'avg_drawdown': float(np.mean([m['max_drawdown'] for m in all_metrics])),
                'avg_win_rate': float(np.mean([m['win_rate'] for m in all_metrics])),
                'avg_reward': float(np.mean([m['reward_metric'] for m in all_metrics])),
                'windows': all_metrics,
            }
        else:
            aggregated = {}
        
        return aggregated


class SystemBenchmark:
    """Complete system benchmark suite"""
    
    def __init__(self):
        self.mc_simulator = MonteCarloSimulator(n_paths=10000, n_steps=252)
        self.wf_engine = WalkForwardEngine(window_size=252, test_size=63)
        logger.info("SystemBenchmark initialized")
    
    def run_full_benchmark(self, symbol: str = 'XAUUSD') -> Dict:
        """
        Execute comprehensive benchmark suite
        
        Returns:
            Dictionary with all benchmark results
        """
        benchmark_results = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'components': {}
        }
        
        # 1. Generate synthetic price paths using Merton Jump Diffusion
        logger.info("1. Generating Monte Carlo paths with Merton Jump Diffusion...")
        S0 = 2000.0  # Gold starting price
        paths = self.mc_simulator.generate_merton_paths(
            S0=S0,
            mu=0.05,  # 5% drift
            sigma=0.15,  # 15% volatility
            jump_lambda=0.1,  # 10% jump probability per year
            jump_mu=0.0,
            jump_sigma=0.05,
            T=1.0
        )
        
        mc_stats = self.mc_simulator.compute_path_statistics()
        benchmark_results['components']['monte_carlo'] = {
            'n_paths': self.mc_simulator.n_paths,
            'n_steps': self.mc_simulator.n_steps,
            'statistics': mc_stats,
        }
        logger.info(f"  MC Results: μ={mc_stats['mean_return']:.4f}, σ={mc_stats['std_return']:.4f}, VaR95={mc_stats['var_95']:.4f}")
        
        # 2. Walk-Forward Analysis
        logger.info("2. Executing Walk-Forward optimization and testing...")
        # Use MC mean path as synthetic historical data
        mean_path = np.mean(paths, axis=0)
        wf_results = self.wf_engine.run_walk_forward_test(mean_path)
        benchmark_results['components']['walk_forward'] = wf_results
        
        if wf_results:
            logger.info(f"  WF Results: avg_return={wf_results.get('avg_return', 0):.4f}, avg_sharpe={wf_results.get('avg_sharpe', 0):.4f}")
        
        # 3. Regime Detection Analysis
        logger.info("3. Analyzing regime detection on mean path...")
        detector = RegimeDetector(window_bars=50)
        regimes, regime_metrics = detector.detect(mean_path)
        benchmark_results['components']['regime_detection'] = regime_metrics
        logger.info(f"  Regime: State-0={regime_metrics['mean_revert_pct']:.1f}%, State-1={regime_metrics['trending_pct']:.1f}%, State-2={regime_metrics['crisis_pct']:.1f}%")
        
        # 4. Hawkes Process Analysis
        logger.info("4. Analyzing Hawkes order flow intensity...")
        hawkes = HawkesPointProcess(alpha=0.6, beta=0.9, lambda_0=1.5)
        # Simulate order events
        n_events = 500
        event_times = np.sort(np.random.uniform(0, 252, n_events))
        hawkes.update_events(event_times)
        time_grid = np.linspace(0, 252, 100)
        intensities = hawkes.compute_intensity(time_grid)
        benchmark_results['components']['hawkes_analysis'] = {
            'n_events': n_events,
            'avg_intensity': float(np.mean(intensities)),
            'max_intensity': float(np.max(intensities)),
            'alpha': hawkes.alpha,
            'beta': hawkes.beta,
        }
        logger.info(f"  Hawkes: avg_intensity={np.mean(intensities):.4f}, max_intensity={np.max(intensities):.4f}")
        
        # 5. QAOA Portfolio Optimization
        logger.info("5. Executing QAOA portfolio optimization...")
        qaoa = QAOAOptimizer(depth=5, learning_rate=0.01)
        n_assets = 3
        returns_vector = np.array([0.08, 0.10, 0.06])  # Expected returns
        cov_matrix = np.array([
            [0.02, 0.005, 0.001],
            [0.005, 0.03, 0.002],
            [0.001, 0.002, 0.015]
        ])
        
        weights = qaoa.optimize_portfolio(returns_vector, cov_matrix, risk_aversion=1.0, iterations=50)
        benchmark_results['components']['qaoa_optimization'] = {
            'optimal_weights': weights.tolist(),
            'n_assets': n_assets,
            'optimization_iterations': 50,
        }
        logger.info(f"  QAOA weights: {weights}")
        
        # 6. Agent Performance Analysis
        logger.info("6. Simulating agent trading on price paths...")
        mm_agent = MarketMakerAgent()
        dir_agent = DirectionalAgent()
        
        # Simple agent simulation
        mm_orders = 0
        dir_orders = 0
        for i in range(1, min(100, len(mean_path))):
            bid_vol = np.random.uniform(1000, 5000)
            ask_vol = np.random.uniform(1000, 5000)
            
            if regimes[i] == 0:  # Market maker in State-0
                orders = mm_agent.generate_orders(mean_path[i], 1.5, bid_vol, ask_vol)
                mm_orders += len(orders)
            
            if regimes[i] == 1:  # Directional in State-1
                state = dir_agent.build_state_representation({
                    'prices': mean_path[max(0, i-20):i],
                    'bid_volume': bid_vol,
                    'ask_volume': ask_vol,
                    'hawkes_intensity': intensities[i % len(intensities)],
                })
                action, size = dir_agent.compute_policy_action(state)
                if action != 'HOLD':
                    dir_orders += 1
        
        benchmark_results['components']['agent_simulation'] = {
            'mm_orders_generated': mm_orders,
            'dir_orders_generated': dir_orders,
            'simulation_bars': 100,
        }
        logger.info(f"  Agents: MM_orders={mm_orders}, DIR_orders={dir_orders}")
        
        # Final summary
        benchmark_results['status'] = 'completed'
        logger.info("Benchmark completed successfully")
        
        return benchmark_results
    
    def export_results(self, results: Dict, filename: str = 'benchmark_results.json') -> bool:
        """Export benchmark results to JSON file"""
        try:
            with open(filename, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            logger.info(f"Results exported to {filename}")
            return True
        except Exception as e:
            logger.error(f"Error exporting results: {e}")
            return False


# Main benchmark execution
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    benchmark = SystemBenchmark()
    results = benchmark.run_full_benchmark('XAUUSD')
    benchmark.export_results(results)
    
    # Print summary
    print("\n" + "="*60)
    print("SOVEREIGN-X CORE OS - BENCHMARK SUMMARY")
    print("="*60)
    print(f"Timestamp: {results['timestamp']}")
    print(f"Symbol: {results['symbol']}")
    print(f"Status: {results['status']}")
    print("\nComponent Results:")
    for component, data in results['components'].items():
        print(f"  [OK] {component}: {type(data).__name__}")
    print("="*60 + "\n")
