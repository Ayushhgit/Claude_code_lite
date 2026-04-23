document.addEventListener('DOMContentLoaded', function() {
  const hero = document.querySelector('.hero');
  hero.addEventListener('mouseover', function() {
    hero.style.backgroundPosition = '0% 0';
  });
  hero.addEventListener('mouseout', function() {
    hero.style.backgroundPosition = '0% 100';
  });
});
