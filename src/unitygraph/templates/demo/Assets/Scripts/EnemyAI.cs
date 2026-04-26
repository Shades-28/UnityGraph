using UnityEngine;

namespace MiniUnity
{
    public class EnemyAI : MonoBehaviour
    {
        [SerializeField] private float _detectionRange = 10.0f;
        [SerializeField] private int _damagePerHit = 10;

        private Transform _playerTransform;

        private void Start()
        {
            var player = GameObject.FindWithTag("Player");
            if (player != null)
            {
                _playerTransform = player.transform;
            }
        }

        private void Update()
        {
            if (_playerTransform == null) return;
            float dist = Vector3.Distance(transform.position, _playerTransform.position);
            if (dist < _detectionRange)
            {
                var health = _playerTransform.GetComponent<HealthSystem>();
                if (health != null)
                {
                    health.TakeDamage(_damagePerHit);
                }
            }
        }
    }
}
