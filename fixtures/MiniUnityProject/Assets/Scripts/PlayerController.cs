using UnityEngine;
using UnityEngine.Events;

namespace MiniUnity
{
    /// <summary>
    /// Player movement and attack controller. The Inspector value of <c>_speed</c>
    /// overrides the code default on the <c>Player</c> GameObject in Main.unity.
    /// </summary>
    public class PlayerController : MonoBehaviour
    {
        [SerializeField] private float _speed = 5.0f;
        [SerializeField] private float _jumpForce = 8.0f;
        [SerializeField] private int _maxHealth = 100;

        private Rigidbody _rigidbody;
        private HealthSystem _health;
        private float _speedMultiplier = 1.0f;

        public float CurrentSpeed => _speed * _speedMultiplier;

        private void Awake()
        {
            _rigidbody = GetComponent<Rigidbody>();
            _health = GetComponent<HealthSystem>();
        }

        private void Start()
        {
            _health.OnDamaged.AddListener(HandleDamaged);
        }

        private void Update()
        {
            float h = Input.GetAxis("Horizontal");
            float v = Input.GetAxis("Vertical");
            Vector3 dir = new Vector3(h, 0f, v) * CurrentSpeed;
            _rigidbody.AddForce(dir);
        }

        public void OnAttackPressed()
        {
            // Hooked to UI_Button.onClick in Main.unity.
        }

        private void HandleDamaged(int amount)
        {
            // Slow effect: assumes speed range [0, 5]. Wrong when Inspector sets _speed = 7.
            _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / 5.0f));
        }
    }
}
