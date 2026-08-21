# Maintainer: jackzasian <jack.zhengzexi@gmail.com>
pkgname=omarchy-eq
pkgver=3.0.0
pkgrel=1
pkgdesc="Per-device PipeWire EQ: measure your speakers, import AutoEq headphone presets, and switch profiles automatically as outputs change"
arch=('any')
url="https://github.com/jackzasian/omarchy-eq"
license=('MIT')
depends=('pipewire' 'pipewire-audio' 'pipewire-pulse' 'libpulse' 'python')
optdepends=(
  'noise-suppression-for-voice: RNNoise microphone chain (omarchy-eq mic)'
  'libnotify: desktop notification when switching profiles'
  'systemd: supervises the filter chains and the auto-switching watcher.
            Without a systemd user session, apply falls back to the pre-v3
            drop-in (omarchy-eq apply --static) and autoswitch must be started
            by hand as omarchy-eq autoswitch run'
)
# No python dependency beyond the interpreter, deliberately. `omarchy-eq fetch`
# talks to the AutoEq database with urllib from the standard library, so the
# whole tool stays installable on a machine with no pip and no venv.
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

check() {
  cd "$pkgname-$pkgver"
  python -m unittest discover -s tests -t tests
}

package() {
  cd "$pkgname-$pkgver"
  install -Dm755 bin/omarchy-eq "$pkgdir/usr/bin/omarchy-eq"
  install -Dm755 omarchy/omarchy-eq-term "$pkgdir/usr/bin/omarchy-eq-term"
  install -d "$pkgdir/usr/share/omarchy-eq/lib"
  install -m644 lib/*.py lib/*.tmpl "$pkgdir/usr/share/omarchy-eq/lib/"
  # Menu snippet is data, not config: Omarchy reads a single user-owned menu
  # file, so this is shipped for the user to merge rather than installed live.
  install -Dm644 omarchy/omarchy-menu.jsonc \
    "$pkgdir/usr/share/omarchy-eq/omarchy-menu.jsonc"
  install -Dm644 omarchy/bindings.lua.snippet \
    "$pkgdir/usr/share/omarchy-eq/bindings.lua.snippet"
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
