# Maintainer: jackzasian <jack.zhengzexi@gmail.com>
pkgname=omarchy-eq
pkgver=2.0.0
pkgrel=1
pkgdesc="Measure laptop speakers with their own microphone, derive an EQ from the measurement, and A/B it live"
arch=('any')
url="https://github.com/jackzasian/omarchy-eq"
license=('MIT')
depends=('pipewire' 'pipewire-audio' 'pipewire-pulse' 'libpulse' 'python')
optdepends=(
  'noise-suppression-for-voice: RNNoise microphone chain (omarchy-eq mic)'
  'libnotify: desktop notification when switching profiles'
)
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
