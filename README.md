# DON Futures Bot - AMP 24/7 Mode

Donchian channel failed-test strategy for MNQ futures on AMP.

## Strategy
- **Entry**: Failed test of Donchian channel (break → reclaim = fade)
- **Exit**: Fixed target OR trailing stop (runner mode)

## Settings (Optimized for AMP)
| Setting | Value | Net P&L |
|---------|-------|---------|
| Stop | 8 pts | -$16 (-$20 w/ commission) |
| Target | 12 pts | +$24 (+$20 w/ commission) |
| Trail Activation | 11 pts | Lock profits near target |
| Trail Distance | 1 pt | Tight trail |
| Commission | $4 RT | AMP MNQ rate |

## Expected Performance
- **Win Rate**: ~65%
- **EV per trade**: +$6
- **Hours**: 23 hrs/day (Sun 6pm → Fri 5pm ET)

## Usage
```bash
# Shadow mode (paper trading)
python gui_v2.py

# Configure AMP credentials in the GUI
```

## Forked From
- [don-futures-topstep](https://github.com/wamppus/don-futures-topstep) - TopStep version with prop firm rules
