(function () {
  var hero = document.querySelector('[data-hero]');
  if (hero) {
    var slides = hero.querySelectorAll('[data-hero-slide]');
    var dots = hero.querySelectorAll('[data-hero-dot]');
    var current = 0;
    var timer = null;
    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function show(index) {
      if (!slides.length) return;
      current = (index + slides.length) % slides.length;
      slides.forEach(function (slide, i) {
        var active = i === current;
        slide.classList.toggle('opacity-100', active);
        slide.classList.toggle('opacity-0', !active);
        slide.classList.toggle('pointer-events-none', !active);
        slide.setAttribute('aria-hidden', active ? 'false' : 'true');
      });
      dots.forEach(function (dot, i) {
        var active = i === current;
        dot.classList.toggle('w-8', active);
        dot.classList.toggle('bg-white', active);
        dot.classList.toggle('w-2.5', !active);
        dot.classList.toggle('bg-white/50', !active);
      });
    }
    function start() {
      if (reduceMotion || slides.length < 2) return;
      stop();
      timer = setInterval(function () { show(current + 1); }, 6000);
    }
    function stop() { if (timer) clearInterval(timer); timer = null; }

    var prev = hero.querySelector('[data-hero-prev]');
    var next = hero.querySelector('[data-hero-next]');
    if (prev) prev.addEventListener('click', function () { show(current - 1); start(); });
    if (next) next.addEventListener('click', function () { show(current + 1); start(); });
    dots.forEach(function (dot) {
      dot.addEventListener('click', function () { show(parseInt(dot.dataset.heroDot, 10)); start(); });
    });
    hero.addEventListener('mouseenter', stop);
    hero.addEventListener('mouseleave', start);
    hero.addEventListener('focusin', stop);
    hero.addEventListener('focusout', start);
    start();
  }

  document.querySelectorAll('[data-carousel]').forEach(function (carousel) {
    var slides = carousel.querySelectorAll('[data-carousel-slide]');
    var dots = carousel.querySelectorAll('[data-carousel-dot]');
    var current = 0;
    var timer = null;
    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function show(index) {
      current = (index + slides.length) % slides.length;
      slides.forEach(function (slide, i) {
        var active = i === current;
        slide.classList.toggle('opacity-100', active);
        slide.classList.toggle('opacity-0', !active);
        slide.classList.toggle('pointer-events-none', !active);
        slide.setAttribute('aria-hidden', active ? 'false' : 'true');
        if (active) slide.removeAttribute('tabindex'); else slide.setAttribute('tabindex', '-1');
      });
      dots.forEach(function (dot, i) {
        var active = i === current;
        dot.classList.toggle('w-6', active);
        dot.classList.toggle('bg-white', active);
        dot.classList.toggle('w-2', !active);
        dot.classList.toggle('bg-white/50', !active);
      });
    }
    function stop() { if (timer) clearInterval(timer); timer = null; }
    function start() {
      if (reduceMotion) return;
      stop();
      timer = setInterval(function () { show(current + 1); }, 5000);
    }

    carousel.querySelector('[data-carousel-prev]').addEventListener('click', function () { show(current - 1); start(); });
    carousel.querySelector('[data-carousel-next]').addEventListener('click', function () { show(current + 1); start(); });
    dots.forEach(function (dot) {
      dot.addEventListener('click', function () { show(parseInt(dot.dataset.carouselDot, 10)); start(); });
    });
    carousel.addEventListener('mouseenter', stop);
    carousel.addEventListener('mouseleave', start);
    carousel.addEventListener('focusin', stop);
    carousel.addEventListener('focusout', start);
    start();
  });

  var dialog = document.querySelector('[data-lightbox]');
  if (dialog && typeof dialog.showModal === 'function') {
    var image = dialog.querySelector('[data-lightbox-image]');
    var caption = dialog.querySelector('[data-lightbox-caption]');
    document.querySelectorAll('[data-lightbox-src]').forEach(function (trigger) {
      trigger.addEventListener('click', function () {
        image.src = trigger.dataset.lightboxSrc;
        image.alt = trigger.dataset.lightboxAlt || '';
        caption.textContent = trigger.dataset.lightboxCaption || '';
        dialog.showModal();
      });
    });
    dialog.addEventListener('click', function (e) { if (e.target === dialog) dialog.close(); });
  }
})();
