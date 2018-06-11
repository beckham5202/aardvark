import tensorflow as tf
import tensorflow.contrib.slim as slim
from nets import nets_factory, resnet_utils, resnet_v2

def patch_resnet_arg_scope (is_training):

    def resnet_arg_scope (weight_decay=0.0001):
      print('\033[91m' + 'Using patched resnet arg scope' + '\033[0m')

      batch_norm_decay=0.9
      batch_norm_epsilon=5e-4
      batch_norm_scale=False
      activation_fn=tf.nn.relu
      use_batch_norm=True

      batch_norm_params = {
          'decay': batch_norm_decay,
          'epsilon': batch_norm_epsilon,
          'scale': batch_norm_scale,
          'updates_collections': tf.GraphKeys.UPDATE_OPS,
          # don't know what it does, but seems improves cifar10 a bit
          #'fused': None,  # Use fused batch norm if possible.
          'is_training': is_training
      }
      with slim.arg_scope(
          [slim.conv2d],
          weights_regularizer=slim.l2_regularizer(weight_decay),
          #Removing following 2 improves cifar10 performance
          #weights_initializer=slim.variance_scaling_initializer(),
          activation_fn=activation_fn,
          normalizer_fn=slim.batch_norm if use_batch_norm else None,
          normalizer_params=batch_norm_params):
        with slim.arg_scope([slim.batch_norm], **batch_norm_params):
          with slim.arg_scope([slim.max_pool2d], padding='SAME') as arg_sc:
            return arg_sc
    return resnet_arg_scope

def patch (is_training):
    asc = patch_resnet_arg_scope(is_training)
    keys = [key for key in nets_factory.arg_scopes_map.keys() if 'resnet_' in key]
    for key in keys:
        nets_factory.arg_scopes_map[key] = asc

def resnet_v2_18 (inputs,
                 num_classes=None,
                 is_training=True,
                 global_pool=True,
                 output_stride=None,
                 reuse=None,
                 include_root_block=True,
                 scope='resnet_v2_18'):
  resnet_v2_block = resnet_v2.resnet_v2_block
  blocks = [
      resnet_v2_block('block1', base_depth=64, num_units=2, stride=2),
      resnet_v2_block('block2', base_depth=128, num_units=2, stride=2),
      resnet_v2_block('block3', base_depth=256, num_units=2, stride=2),
      resnet_v2_block('block4', base_depth=512, num_units=2, stride=1),
  ]
  return resnet_v2.resnet_v2(
      inputs,
      blocks,
      num_classes,
      is_training,
      global_pool,
      output_stride,
      include_root_block=include_root_block,
      reuse=reuse,
      scope=scope)

def resnet_v2_18_cifar (inputs, num_classes=None, is_training=True,
                        reuse=None, scope='resnet_v2_18_cifar'):
    return resnet_v2_18(inputs, num_classes, is_training, reuse=reuse, include_root_block=False, scope=scope)


def extend ():
    nets_factory.networks_map['resnet_v2'] = resnet_v2
    nets_factory.networks_map['resnet_v2_18_cifar'] = resnet_v2_18_cifar
    nets_factory.arg_scopes_map['resnet_18'] = resnet_v2.resnet_arg_scope
    nets_factory.arg_scopes_map['resnet_v2_18_cifar'] = resnet_v2.resnet_arg_scope
    pass
