using UnityEngine;
using UnityEngine.Events;

namespace MiniUnity
{
    [System.Serializable]
    public class DamagedEvent : UnityEvent<int> { }

    public class HealthSystem : MonoBehaviour
    {
        [SerializeField] private int _maxHealth = 100;
        [SerializeField] private DamagedEvent _onDamaged = new DamagedEvent();

        private int _current;

        public UnityEvent<int> OnDamaged => _onDamaged;

        private void Awake()
        {
            _current = _maxHealth;
        }

        public void TakeDamage(int amount)
        {
            _current = Mathf.Max(0, _current - amount);
            _onDamaged.Invoke(amount);
        }
    }
}
