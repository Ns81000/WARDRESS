/* ============================================================
   Wardress — landing page interactions
   GSAP + ScrollTrigger + Lenis. Every effect honors
   prefers-reduced-motion.
   ============================================================ */

(() => {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const hasGSAP = typeof window.gsap !== "undefined";
  const gsap = window.gsap;
  const ScrollTrigger = window.ScrollTrigger;

  if (hasGSAP && ScrollTrigger) gsap.registerPlugin(ScrollTrigger);

  /* ==========================================================
     1. Lenis smooth scroll, wired to ScrollTrigger.
     ========================================================== */
  let lenis = null;
  if (!reduceMotion && typeof window.Lenis !== "undefined") {
    lenis = new window.Lenis({
      duration: 1.1,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      smoothWheel: true,
    });
    if (hasGSAP && ScrollTrigger) {
      lenis.on("scroll", ScrollTrigger.update);
      gsap.ticker.add((time) => lenis.raf(time * 1000));
      gsap.ticker.lagSmoothing(0);
    } else {
      const raf = (t) => { lenis.raf(t); requestAnimationFrame(raf); };
      requestAnimationFrame(raf);
    }
  }

  // Anchor links routed through Lenis so smooth-scroll stays consistent.
  document.querySelectorAll('a[href^="#"]').forEach((a) => {
    a.addEventListener("click", (e) => {
      const id = a.getAttribute("href");
      if (id.length < 2) return;
      const target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      const top = target.getBoundingClientRect().top + window.scrollY - (68 + 16);
      if (lenis) lenis.scrollTo(top, { duration: 1.2 });
      else window.scrollTo({ top, behavior: reduceMotion ? "auto" : "smooth" });
    });
  });

  /* ==========================================================
     2. Split-text hero title — words rise from a clipped line.
     ========================================================== */
  document.querySelectorAll("[data-split]").forEach((el) => {
    const words = el.textContent.trim().split(/\s+/);
    el.textContent = "";
    words.forEach((word, i) => {
      const clip = document.createElement("span");
      clip.className = "w";
      const inner = document.createElement("span");
      inner.textContent = word;
      inner.style.transitionDelay = `${140 + i * 70}ms`;
      clip.appendChild(inner);
      el.appendChild(clip);
      if (i < words.length - 1) el.appendChild(document.createTextNode(" "));
    });
    requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("in")));
  });

  /* ==========================================================
     3. Scroll reveal — IntersectionObserver adds .in once.
     ========================================================== */
  const revealables = document.querySelectorAll(".reveal");
  if (reduceMotion) {
    revealables.forEach((el) => el.classList.add("in"));
  } else {
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        const d = e.target.getAttribute("data-delay");
        if (d) e.target.style.setProperty("--rd", `${d}ms`);
        e.target.classList.add("in");
        io.unobserve(e.target);
      }
    }, { threshold: 0.12, rootMargin: "0px 0px -48px 0px" });
    revealables.forEach((el) => io.observe(el));
  }

  /* ==========================================================
     4. Count-up stats.
     ========================================================== */
  const counters = document.querySelectorAll("[data-count]");
  const cio = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      cio.unobserve(e.target);
      const el = e.target;
      const end = parseFloat(el.dataset.count);
      const isFloat = !Number.isInteger(end);
      if (reduceMotion) { el.textContent = isFloat ? end.toFixed(2) : end; continue; }
      const t0 = performance.now();
      const dur = 1500;
      const tick = (t) => {
        const p = Math.min((t - t0) / dur, 1);
        const eased = 1 - Math.pow(1 - p, 4);
        const val = end * eased;
        el.textContent = isFloat ? val.toFixed(2) : Math.round(val);
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }
  }, { threshold: 0.6 });
  counters.forEach((el) => cio.observe(el));

  /* ==========================================================
     5. Nav — scrolled state + scroll progress rail.
     ========================================================== */
  const nav = document.querySelector(".nav");
  const progress = document.querySelector(".scroll-progress");
  let ticking = false;
  const onScroll = () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      if (nav) nav.classList.toggle("scrolled", window.scrollY > 24);
      if (progress) {
        const max = document.documentElement.scrollHeight - window.innerHeight;
        progress.style.transform = `scaleX(${max > 0 ? window.scrollY / max : 0})`;
      }
      ticking = false;
    });
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ==========================================================
     6. Copy buttons.
     ========================================================== */
  document.querySelectorAll(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const target = document.getElementById(btn.dataset.copy);
      if (!target) return;
      try {
        await navigator.clipboard.writeText(target.textContent.trim());
        btn.classList.add("copied");
        setTimeout(() => btn.classList.remove("copied"), 1600);
      } catch { /* clipboard unavailable — ignore */ }
    });
  });


  /* ==========================================================
     8. GSAP scroll choreography.
     ========================================================== */
  if (hasGSAP && ScrollTrigger && !reduceMotion) {

    // 8a. Hero art parallax drift.
    const art = document.querySelector(".hero-art");
    if (art) {
      gsap.to(art, {
        y: 90,
        ease: "none",
        scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom top", scrub: true },
      });
    }

    // 8b. Layer tiles stagger in as the grid scrolls into view.
    gsap.from(".layer-tile", {
      opacity: 0,
      y: 32,
      duration: 0.55,
      stagger: 0.06,
      ease: "power2.out",
      scrollTrigger: { trigger: ".layer-grid", start: "top 82%", toggleActions: "play none none reverse" },
    });

    // 8d. Architecture nodes cascade.
    gsap.utils.toArray(".arch-tier").forEach((tier) => {
      gsap.from(tier.querySelectorAll(".arch-node"), {
        opacity: 0, y: 24, duration: 0.55, stagger: 0.08, ease: "power2.out",
        scrollTrigger: { trigger: tier, start: "top 85%", toggleActions: "play none none reverse" },
      });
    });

    // 8e. Section headings — subtle rise on the eyebrow + h2.
    gsap.utils.toArray(".stack-item").forEach((item, i) => {
      gsap.from(item, {
        opacity: 0, y: 24, duration: 0.5, ease: "power2.out",
        scrollTrigger: { trigger: ".stack-grid", start: "top 82%", toggleActions: "play none none reverse" },
        delay: (i % 7) * 0.04,
      });
    });

    // 8f. RBAC rows wipe in.
    gsap.from(".rbac-table tbody tr", {
      opacity: 0, x: -18, duration: 0.5, stagger: 0.06, ease: "power2.out",
      scrollTrigger: { trigger: ".rbac-table", start: "top 82%", toggleActions: "play none none reverse" },
    });

    ScrollTrigger.refresh();
  }

  /* ==========================================================
     9. Desktop lock — this immersive build is desktop-only.
        Small screens get a permanent, non-dismissable overlay.
     ========================================================== */
  const deskLock = document.getElementById("deskLock");
  const applyDeskLock = () => {
    const small = window.innerWidth <= 900;
    document.body.classList.toggle("desk-locked", small);
    if (deskLock) deskLock.classList.toggle("visible", small);
  };
  applyDeskLock();
  window.addEventListener("resize", applyDeskLock, { passive: true });
  window.addEventListener("orientationchange", applyDeskLock, { passive: true });
})();
